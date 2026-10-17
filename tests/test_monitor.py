from datetime import datetime, timedelta
import json
from pathlib import Path

import pytest
from industry_monitor_core.web import FetchError, LOCAL_TZ, Page
from shaanxi_policy.collect import collect, empty_state
from shaanxi_policy.extract import deadline_candidates, deadline_state, discover, extract, relevant
from shaanxi_policy.report import payload, render
from shaanxi_policy.http import PolicyClient

SOURCE = json.loads(Path("config/sources.json").read_text(encoding="utf-8"))[0]
NOW = datetime(2026, 10, 15, 9, tzinfo=LOCAL_TZ)
URL = SOURCE["seeds"][0]


def page(text, url=URL):
    return Page(url, 200, "text/html", text.encode())


def article(extra=""):
    # Minimal synthetic fixture with the real deadline roles; not a page archive.
    return page('''<meta name="ArticleTitle" content="西安市中小企业数字化改造项目申报通知">
      <meta name="PubDate" content="2026-09-11 18:25"><meta name="robots" content="noarchive">
      <div id="article"><p>二、奖补范围及标准</p><p>一、申报条件</p><p>企业须在2026年9月15日前完成改造。合同不得早于2024年10月18日。</p>
      <p>申报单位须于9月25日前将申报资料提交至辖区工业和信息化主管部门。</p>
      <p>区县主管部门9月28日之前正式行文推荐报送至市工信局。</p>
      <p>对于审核不通过的项目，申报单位须于10月8日前调整或补充资料。</p>
      <p>按照不超过核定投入费用的50%给予补助，最高不超过100万元。</p>
      <a href="/web_files/gxj/file/2026/09/11/example.docx">申报材料</a>''' + extra + '</div>')


def test_reference_deadline_roles_and_expiry():
    r = extract(article(), SOURCE)
    d = deadline_state(r, NOW.date())
    assert d["date"] == "2026-09-25"
    assert d["status"] == "已过原文截止日期"
    assert {(x["date"], x["kind"]) for x in r["dates"]} >= {
        ("2026-10-08", "补正截止"), ("2026-09-28", "主管部门报送"), ("2026-09-15", "项目条件日期")}
    assert "html" not in r and "body" not in r and "text" not in r
    assert len(r["attachments"]) == 1
    assert "50%" in r["highlights"][0]


@pytest.mark.parametrize("text", [
    "市级发展改革部门将申报项目汇总表于10月15日前报送省发展改革委。",
    "项目必须于2026年10月15日前完成。",
    "公示至2026年10月15日，企业可以反馈意见。",
    "申报时间为9月1日至9月25日。",
])
def test_other_dates_never_become_enterprise_cutoff(text):
    r = {"category": "申报与征集", "dates": deadline_candidates(text, "2026-09-01")}
    assert deadline_state(r, NOW.date())["date"] is None


def test_conflicting_deadlines_and_missing_year_require_review():
    r = {"category": "申报与征集", "dates": deadline_candidates("申报单位须于10月20日前提交线上材料。申报单位须于10月22日前报送纸质材料。", "2026-10-01")}
    assert deadline_state(r, NOW.date())["date"] is None
    assert deadline_candidates("申报截止1月15日。", "2026-12-20")[0]["kind"] == "日期年份待核实"


def test_deadline_is_recomputed_for_each_report_date():
    r = extract(article(), SOURCE)
    assert deadline_state(r, datetime(2026, 9, 20).date())["status"] == "7天内截止"
    assert deadline_state(r, datetime(2026, 9, 25).date())["status"] == "今日截止，时点需核实"
    assert deadline_state(r, NOW.date())["status"] == "已过原文截止日期"


def test_relevance_excludes_procurement_and_personnel():
    assert relevant("关于开展企业研发投入奖补项目申报工作的通知")
    assert relevant("关于开展国家级绿色工厂推荐的通知")
    assert not relevant("关于工业技术服务采购项目的通知")
    assert not relevant("关于科技局人员任职的通知")


def test_discovery_scoped_hosts_and_dom_drift():
    listing = page(f'<article class="card"><h3 class="title"><a href="{URL}">企业数字化改造项目申报通知</a><a href="https://evil.example/gzdt/tzgg/123.html">企业补贴申报通知</a></h3></article>', SOURCE["url"])
    assert [l["url"] for l in discover(listing, SOURCE)] == [URL]
    with pytest.raises(FetchError):
        discover(page('<title>政府首页</title>'), SOURCE)


def test_no_snippet_suppresses_derived_quotes():
    p = article()
    p.payload = p.payload.replace(b'content="noarchive"', b'content="nosnippet"')
    r = extract(p, SOURCE)
    assert r["highlights"] == [] and r["dates"] == []


class Client:
    def __init__(self):
        self.failed = False
        self.changed = False

    def fetch(self, url, source):
        if self.failed:
            raise FetchError("Page HTTP 403; no bypass or immediate retry")
        if url == source["url"]:
            return page(f'<article class="card"><h3 class="title"><a href="{URL}">企业数字化改造项目申报通知</a></h3></article>', url)
        return article('<p>补助最高调整为80万元。</p>' if self.changed else '')


def test_baseline_incremental_updates_and_failure_retention():
    client = Client()
    state, health = collect([SOURCE], empty_state(), NOW, client=client)
    assert payload(state, health, NOW)["counts"]["baseline"] == 1
    assert payload(state, health, NOW)["counts"]["discovered"] == 0
    again, health = collect([SOURCE], state, NOW, client=client)
    assert again["events"] == state["events"]
    client.changed = True
    updated, health = collect([SOURCE], again, NOW + timedelta(days=1), client=client)
    assert payload(updated, health, NOW + timedelta(days=1))["counts"]["updated"] == 1
    client.failed = True
    failed, health = collect([SOURCE], updated, NOW + timedelta(days=2), client=client)
    assert failed["records"] == updated["records"]
    assert health[0]["status"] == "failed"
    assert payload(failed, health, NOW + timedelta(days=2))["counts"]["failed"] == 1


def test_unfinished_baseline_queue_remains_baseline():
    other = URL.replace("2098358849019383809", "2098358849019383810")
    class Two(Client):
        def fetch(self, url, source):
            if url == source["url"]:
                return page(f'<article class="card"><h3 class="title"><a href="{URL}">企业政策申报通知</a><a href="{other}">企业补贴申报通知</a></h3></article>', url)
            p = article()
            p.url = url
            return p
    state, health = collect([SOURCE], empty_state(), NOW, budget=1, client=Two())
    assert health[0]["pending"] == 1 and health[0]["status"] == "partial"
    state, health = collect([SOURCE], state, NOW + timedelta(days=1), budget=1, client=Two())
    r = payload(state, health, NOW + timedelta(days=1))
    assert r["counts"]["baseline"] == 1 and r["counts"]["discovered"] == 0


def test_report_escapes_remote_markup_and_excludes_internal_hashes():
    state, health = collect([SOURCE], empty_state(), NOW, client=Client())
    state["records"][URL]["title"] = '<img src=x onerror=alert(1)>'
    r = payload(state, health, NOW)
    assert "content_hash" not in r["policies"][0]
    page_text = render(r, [r["date"]])
    assert '<img src=x' not in page_text
    assert '&lt;img' in page_text


def test_legitimate_validation_policy_title_does_not_disable_challenge_checks(monkeypatch):
    import shaanxi_policy.http as transport
    good = article()
    good.payload = b'<title>' + '关于概念验证中心管理办法的通知'.encode() + b'</title>' + good.payload
    def simulated_core(self, url, source, content_types):
        self.last_page = good
        raise FetchError("Challenge/login page; manual review required")
    monkeypatch.setattr(transport.SafeClient, "fetch", simulated_core)
    client = PolicyClient()
    assert client.fetch(URL, SOURCE) is good
    good.payload = good.payload.replace('概念验证中心'.encode(), '概念验证中心验证码'.encode())
    with pytest.raises(FetchError):
        client.fetch(URL, SOURCE)


def test_policy_client_retries_transient_connection_errors(monkeypatch):
    import shaanxi_policy.http as transport
    calls = []
    good = article()
    def flaky(self, url, source, content_types=None):
        calls.append(url)
        if len(calls) < 3:
            raise FetchError("Network/TLS failure: ConnectionError")
        return good
    monkeypatch.setattr(transport.SafeClient, "fetch", flaky)
    monkeypatch.setattr(transport.time, "sleep", lambda seconds: None)
    assert PolicyClient().fetch(URL, SOURCE) is good
    assert len(calls) == 3


def test_policy_client_does_not_retry_access_challenges(monkeypatch):
    import shaanxi_policy.http as transport
    calls = []
    def blocked(self, url, source, content_types=None):
        calls.append(url)
        raise FetchError("Challenge/login page; manual review required")
    monkeypatch.setattr(transport.SafeClient, "fetch", blocked)
    with pytest.raises(FetchError, match="Challenge/login"):
        PolicyClient().fetch(URL, SOURCE)
    assert len(calls) == 1
