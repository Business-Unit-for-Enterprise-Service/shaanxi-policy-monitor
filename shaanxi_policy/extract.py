"""Conservative policy metadata extraction; article bodies are never persisted."""

import re
from datetime import date
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from industry_monitor_core.web import FetchError, digest, meta_content, parse_date, source_link

EXCLUDE = re.compile(r"采购|招标|中标|成交|遴选结果|招聘|录用|任职|任免|备案公告|监督检查情况|办公用房|体检|课题承担单位")
TOPICS = re.compile(r"企业|产业|制造|工业|科技|技术|研发|创新|数字|智能|算力|绿色|节能|服务业|税|融资|金融|人才|成果转化|中试|概念验证|园区")
ACTIONS = re.compile(r"申报|补贴|补助|奖补|奖励|征集|认定|公示|名单|目录|政策|措施|办法|意见|通知|工作指引|减免|专项|支持")
DATE_TOKEN = re.compile(r"(?:(20\d{2})\s*[年/.-]\s*)?(\d{1,2})\s*[月/.-]\s*(\d{1,2})\s*日?")


def clean(value, limit=240):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    value = re.sub(r"\b1[3-9]\d{9}\b|\b0\d{2,3}[-— ]?\d{7,8}\b", "[电话略]", value)
    return value[:limit] + ("…" if len(value) > limit else "")


def relevant(title):
    return not EXCLUDE.search(title) and bool(TOPICS.search(title) and ACTIONS.search(title))


def category(title):
    if re.search(r"公示|公布|名单|验收", title):
        return "结果公示与认定"
    if re.search(r"征求|听证", title):
        return "政策征求意见"
    if re.search(r"申报|征集|申请|遴选", title):
        return "申报与征集"
    return "政策措施与解读"


def restrictions(soup):
    return " ".join(n.get("content", "") for n in soup.select('meta[name="robots"]')).lower()


def discover(page, source):
    soup = BeautifulSoup(page.html, "html.parser")
    if "nofollow" in restrictions(soup) or "none" in restrictions(soup):
        raise FetchError("Listing prohibits automated link following")
    anchors = soup.select(source["link_selector"])
    matched = {}
    for anchor in anchors:
        try:
            url = source_link(anchor["href"], page.url, source)
        except ValueError:
            continue
        if re.fullmatch(source["article_pattern"], urlsplit(url).path):
            matched[url] = clean(anchor.get("title") or anchor.get_text(" ", strip=True), 250)
    if not matched:
        raise FetchError("Reviewed listing contains no matching article links")
    if len(matched) > 150:
        raise FetchError("Listing exceeds reviewed link budget")
    return [{"url": u, "title": t} for u, t in matched.items() if relevant(t)]


def deadline_candidates(text, published):
    """Keep dated evidence; only explicit applicant submission can set a cutoff.

    A recommendation, completion, consultation, or correction date never sets
    the enterprise cutoff. Multiple distinct applicant dates require review.
    Missing years use the publication year and are explicitly marked inferred.
    """
    result = []
    for sentence in re.split(r"[。；;\n]", text):
        sentence = clean(sentence, 4000)
        if not sentence:
            continue
        for match in DATE_TOKEN.finditer(sentence):
            explicit_year, month, day = match.groups()
            if not explicit_year and not published:
                continue
            try:
                parsed = date(int(explicit_year or published[:4]), int(month), int(day))
            except ValueError:
                continue
            # The whole sentence is intentionally considered, even if it makes
            # an ambiguous departmental/applicant deadline require review.
            if re.search(r"补正|补充|修改|调整|审核不通过", sentence):
                kind = "补正截止"
            elif re.search(r"区县|市级|各市|各设区市|主管部门|发展改革部门", sentence[:match.start()]) and re.search(r"推荐|报送省|报送市|正式行文|汇总", sentence):
                kind = "主管部门报送"
            elif re.search(r"完成|完工|合同|签订|注册|成立", sentence) and not re.search(r"提交|填报|报送|申报截止", sentence):
                kind = "项目条件日期"
            elif re.search(r"公示|征求意见|反馈意见|听证", sentence):
                kind = "公示或征求意见"
            elif (re.search(r"申报单位|申报企业|企业须|企业应|申请单位|申请人|申报截止|申报时间|申报期限", sentence)
                  and re.search(r"提交|填报|报送|截止|期限|之前|日前", sentence)
                  and not re.search(r"推荐报送|起至|至.*月|—|～", sentence)):
                kind = "企业申报截止"
            else:
                continue
            # Avoid silently rolling a missing year across New Year.
            if not explicit_year and parsed < date.fromisoformat(published) and (date.fromisoformat(published) - parsed).days > 180:
                kind = "日期年份待核实"
            item = {"date": parsed.isoformat(), "kind": kind, "year_inferred": not bool(explicit_year), "evidence": clean(sentence, 240)}
            if not any(i["date"] == item["date"] and i["kind"] == kind for i in result):
                result.append(item)
    return result[:20]


def deadline_state(record, on_date):
    if record["category"] != "申报与征集":
        return {"date": None, "status": "不适用", "evidence": ""}
    candidates = [c for c in record.get("dates", []) if c["kind"] == "企业申报截止"]
    unique = {c["date"] for c in candidates}
    if len(unique) != 1:
        return {"date": None, "status": "截止时间待核实", "evidence": "存在多个日期" if unique else "未识别到明确的企业申报截止日期，请查原文或附件"}
    cutoff = date.fromisoformat(candidates[0]["date"])
    remaining = (cutoff - on_date).days
    status = "已过原文截止日期" if remaining < 0 else "今日截止，时点需核实" if remaining == 0 else "7天内截止" if remaining <= 7 else "尚未到原文截止日期"
    return {"date": cutoff.isoformat(), "status": status, "evidence": candidates[0]["evidence"], "year_inferred": candidates[0]["year_inferred"]}


def extract(page, source):
    soup = BeautifulSoup(page.html, "html.parser")
    robots = restrictions(soup)
    if "noindex" in robots or "none" in robots:
        raise FetchError("Article prohibits indexing")
    body = soup.select_one(source["body_selector"])
    if body is None:
        raise FetchError("Reviewed article body selector did not match")
    for tag in body.select("script, style, noscript"):
        tag.decompose()
    title = meta_content(soup, ["ArticleTitle", "og:title"])
    title = BeautifulSoup(title, "html.parser").get_text(" ", strip=True) if title else soup.title.get_text(" ", strip=True).split("--")[0] if soup.title else ""
    title = clean(title, 280)
    if not title:
        raise FetchError("Missing article title")
    published = parse_date(meta_content(soup, ["PubDate", "publishdate", "date"]))
    publication_basis = "页面元数据"
    if not published:
        match = re.search(r"/t(20\d{2})(\d{2})(\d{2})_", page.url)
        published = parse_date("-".join(match.groups())) if match else None
        publication_basis = "原文URL日期，待核实" if published else "未识别"
    paragraphs = [p.get_text(" ", strip=True) for p in body.select("p")]
    text = "\n".join(paragraphs) if paragraphs else body.get_text(" ", strip=True)
    if len(text.strip()) < 40:
        raise FetchError("Article body is unexpectedly empty or image-only")
    suppressed = "nosnippet" in robots or bool(re.search(r"max-snippet\s*:\s*0", robots))
    sentences = [clean(s, 220) for s in re.split(r"[。\n]", text) if s.strip()]
    highlights = []
    if not suppressed:
        for pattern in [r"给予|补助|奖补|最高|不超过.*万元|税额", r"申报条件|申报对象|独立法人|申报单位|申报企业"]:
            selected = next((s for s in sentences if len(s) >= 25 and re.search(pattern, s)), None)
            if selected and selected not in highlights:
                highlights.append(selected)
    attachments = []
    for a in body.select("a[href]"):
        try:
            link = source_link(a["href"], page.url, source)
        except ValueError:
            continue
        if re.search(r"\.(pdf|docx?|xlsx?|zip|rar)$", urlsplit(link).path, re.I):
            attachments.append({"title": clean(a.get_text(" ", strip=True) or "附件", 120), "url": link})
    dates = [] if suppressed else deadline_candidates(text, published)
    return {
        "id": digest(page.url)[:20], "url": page.url, "title": title,
        "source_id": source["id"], "source_name": source["name"], "region": source["region"],
        "published_date": published, "publication_basis": publication_basis,
        "category": category(title), "highlights": highlights, "dates": dates,
        "attachments": attachments[:12], "snippet_suppressed": suppressed,
        "content_hash": digest(title + "\n" + str(published) + "\n" + text + "\n" + str(attachments)),
    }
