"""Keep core transport bounds, narrow one known Chinese title false positive."""

import re
import time
from bs4 import BeautifulSoup
from industry_monitor_core.web import FetchError, SafeClient, meta_content


class PolicyClient(SafeClient):
    def _raw(self, url, delay=None):
        result = super()._raw(url, delay)
        self.last_page = result[0]
        return result

    def fetch(self, url, source, content_types=None):
        self.last_page = None
        last_error = None
        for attempt in range(3):
            try:
                return super().fetch(url, source, content_types)
            except FetchError as error:
                last_error = error
                if str(error) != "Network/TLS failure: ConnectionError" or attempt == 2:
                    break
                # A runner can lose a public government host during a transient
                # TLS/DNS failure. Clear only this host's robots cache and retry
                # with the same bounded client, without bypassing TLS or robots.
                self.robot_cache.pop(url.split("/")[2], None)
                time.sleep(2 ** attempt)
        error = last_error
        # Core's generic title check matches any occurrence of 验证. A
        # concept-validation policy is an ordinary article, not a CAPTCHA.
        # Inspect the already-fetched response; never retry a blocked URL.
        page = self.last_page
        if str(error) != "Challenge/login page; manual review required" or page is None or page.status != 200:
            raise error
        soup = BeautifulSoup(page.html, "html.parser")
        title = soup.title.get_text() if soup.title else ""
        remaining = re.sub(r"概念验证|中试验证", "", title)
        body = soup.select_one(source["body_selector"])
        if (remaining != title
            and not re.search(r"captcha|access denied|just a moment|验证|访问受限|forbidden", remaining, re.I)
            and meta_content(soup, ["ArticleTitle"]) and meta_content(soup, ["PubDate"])
            and body is not None and len(body.get_text(strip=True)) > 100):
            return page
        raise error

