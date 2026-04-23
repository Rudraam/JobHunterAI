"""
LinkedIn Job Scraper -- multi-strategy, login-wall bypass.

Strategy order (fastest/no-auth first):
  1. Guest API  -- linkedin.com/jobs-guest/jobs/api/jobPosting/{id}
  2. Mobile UA  -- mobile user-agent sometimes skips the login wall
  3. Playwright -- headless browser with LINKEDIN_LI_AT_COOKIE or LINKEDIN_COOKIES
  4. Third-party -- SCRAPIN_API_KEY or RAPID_API_KEY
"""

import asyncio
import json
import os
import re
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup


class LinkedInScraper:

    HEADERS_DESKTOP = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    def is_login_wall(self, text: str) -> bool:
        login_signals = [
            "sign in with apple",
            "sign in with a passkey",
            "user agreement",
            "privacy policy",
            "cookie policy",
            "forgot password",
            "keep me logged in",
            "new to linkedin",
            "join now",
            "by clicking continue",
        ]
        text_lower = text.lower()
        hits = sum(1 for signal in login_signals if signal in text_lower)
        return hits >= 3

    def extract_job_id(self, url: str) -> Optional[str]:
        patterns = [
            r"/jobs/view/(\d+)",
            r"currentJobId=(\d+)",
            r"/jobs/search/.*?(\d{10,})",
            r"-(\d{10,})/?$",
            r"jobId=(\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    # -- Strategy 1: LinkedIn Guest API --------------------------------------

    async def strategy_guest_api(self, job_id: str) -> Optional[str]:
        api_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
        headers = {
            **self.HEADERS_DESKTOP,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.linkedin.com/jobs/",
        }
        html = None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    api_url, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status != 200:
                        print(f"    Guest API returned {resp.status}")
                        return None
                    html = await resp.text()
        except Exception as e:
            print(f"    Guest API request error: {e}")
            return None

        try:
            soup = BeautifulSoup(html, "html.parser")
            parts = []

            title_el = soup.find("h2", class_=re.compile(r"top-card-layout__title"))
            if title_el:
                parts.append(f"Job Title: {title_el.get_text(strip=True)}")

            company_el = soup.find("a", class_=re.compile(r"topcard__org-name"))
            if company_el:
                parts.append(f"Company: {company_el.get_text(strip=True)}")

            location_el = soup.find("span", class_=re.compile(r"topcard__flavor--bullet"))
            if location_el:
                parts.append(f"Location: {location_el.get_text(strip=True)}")

            desc_el = (
                soup.find("div", class_=re.compile(r"description__text"))
                or soup.find("div", {"class": "show-more-less-html__markup"})
                or soup.find("section", class_=re.compile(r"description"))
            )
            if desc_el:
                parts.append(f"\nJob Description:\n{desc_el.get_text(separator=chr(10), strip=True)}")

            combined = "\n".join(parts)
            if combined and not self.is_login_wall(combined) and len(combined) > 200:
                print(f"    [OK] Guest API succeeded ({len(combined)} chars)")
                return combined

            return None
        except Exception as e:
            print(f"    Guest API parse error: {e}")
            return None

    # -- Strategy 2: Mobile User-Agent ---------------------------------------

    async def strategy_mobile_ua(self, url: str) -> Optional[str]:
        mobile_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.6261.105 Mobile Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        html = None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=mobile_headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                    allow_redirects=True,
                ) as resp:
                    html = await resp.text()
        except Exception as e:
            print(f"    Mobile UA request error: {e}")
            return None

        try:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)

            if not self.is_login_wall(text) and len(text) > 300:
                print(f"    [OK] Mobile UA succeeded ({len(text)} chars)")
                return text
            return None
        except Exception as e:
            print(f"    Mobile UA parse error: {e}")
            return None

    # -- Strategy 3: Playwright with cookies ---------------------------------

    async def strategy_playwright(self, url: str) -> Optional[str]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            print("    Playwright not installed, skipping")
            return None

        li_at = os.getenv("LINKEDIN_LI_AT_COOKIE")
        cookies_json = os.getenv("LINKEDIN_COOKIES")

        if not li_at and not cookies_json:
            print("    No LinkedIn cookies set (LINKEDIN_LI_AT_COOKIE / LINKEDIN_COOKIES), skipping")
            return None

        try:
            if li_at:
                cookies = [{"name": "li_at", "value": li_at, "domain": ".linkedin.com", "path": "/"}]
            else:
                cookies = json.loads(cookies_json)  # type: ignore[arg-type]

            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=self.HEADERS_DESKTOP["User-Agent"]
                )
                await context.add_cookies(cookies)
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)

                try:
                    see_more = page.locator("button:has-text('See more')")
                    if await see_more.count() > 0:
                        await see_more.first.click()
                        await asyncio.sleep(1)
                except Exception:
                    pass

                content = await page.evaluate("""() => {
                    const desc = document.querySelector(
                        '.description__text, .show-more-less-html__markup, ' +
                        '[class*="description"], .jobs-description'
                    );
                    const title = document.querySelector(
                        'h1, .top-card-layout__title, .jobs-unified-top-card__job-title'
                    );
                    const company = document.querySelector(
                        '.topcard__org-name-link, .jobs-unified-top-card__company-name'
                    );
                    return {
                        title: title ? title.innerText.trim() : '',
                        company: company ? company.innerText.trim() : '',
                        description: desc ? desc.innerText.trim() : document.body.innerText
                    };
                }""")

                await browser.close()

            text = (
                f"Job Title: {content.get('title', '')}\n"
                f"Company: {content.get('company', '')}\n"
                f"\nJob Description:\n{content.get('description', '')}"
            )
            if not self.is_login_wall(text) and len(text) > 300:
                print(f"    [OK] Playwright succeeded ({len(text)} chars)")
                return text
            return None
        except Exception as e:
            print(f"    Playwright error: {e}")
            return None

    # -- Strategy 4: Third-party API -----------------------------------------

    async def strategy_third_party_api(self, url: str) -> Optional[str]:
        scrapin_key = os.getenv("SCRAPIN_API_KEY")
        if scrapin_key:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://api.scrapin.io/enrichment/job",
                        json={"url": url},
                        headers={"x-api-key": scrapin_key},
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("job", {}).get("description"):
                                jd = data["job"]
                                text = (
                                    f"Job Title: {jd.get('title', '')}\n"
                                    f"Company: {jd.get('company', {}).get('name', '')}\n"
                                    f"Location: {jd.get('location', '')}\n"
                                    f"\nJob Description:\n{jd.get('description', '')}"
                                )
                                print(f"    [OK] Scrapin.io API succeeded ({len(text)} chars)")
                                return text
            except Exception as e:
                print(f"    Scrapin.io error: {e}")

        rapid_key = os.getenv("RAPID_API_KEY")
        if rapid_key:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        "https://linkedin-data-api.p.rapidapi.com/get-job-details",
                        params={"url": url},
                        headers={
                            "X-RapidAPI-Key": rapid_key,
                            "X-RapidAPI-Host": "linkedin-data-api.p.rapidapi.com",
                        },
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            desc = data.get("description", "") or data.get("jobDescription", "")
                            if desc and len(desc) > 200:
                                text = (
                                    f"Job Title: {data.get('title', '')}\n"
                                    f"Company: {data.get('company', {}).get('name', '')}\n"
                                    f"\nJob Description:\n{desc}"
                                )
                                print(f"    [OK] RapidAPI succeeded ({len(text)} chars)")
                                return text
            except Exception as e:
                print(f"    RapidAPI error: {e}")

        return None

    # -- Main Entry ----------------------------------------------------------

    async def scrape(self, url: str) -> dict:
        print(f"  Scraping LinkedIn URL: {url}")
        job_id = self.extract_job_id(url)
        print(f"  Extracted job ID: {job_id}")

        raw_text = None

        if job_id:
            print("  Trying Strategy 1: Guest API...")
            raw_text = await self.strategy_guest_api(job_id)

        if not raw_text:
            print("  Trying Strategy 2: Mobile UA...")
            raw_text = await self.strategy_mobile_ua(url)

        if not raw_text:
            print("  Trying Strategy 3: Playwright...")
            raw_text = await self.strategy_playwright(url)

        if not raw_text:
            print("  Trying Strategy 4: Third-party API...")
            raw_text = await self.strategy_third_party_api(url)

        if not raw_text or self.is_login_wall(raw_text):
            raise Exception(
                "All LinkedIn scraping strategies failed. "
                "To fix: set LINKEDIN_LI_AT_COOKIE in your .env (copy the li_at cookie value "
                "from linkedin.com -> DevTools -> Application -> Cookies). "
                "Or set SCRAPIN_API_KEY for a third-party fallback."
            )

        return {
            "raw_text": raw_text[:8000],
            "url": url,
            "job_id": job_id,
            "source": "linkedin",
        }
