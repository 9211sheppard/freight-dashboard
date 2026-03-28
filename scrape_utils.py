"""Shared scraping helpers for the dashboard scrapers."""

from __future__ import annotations

import logging
import os
import random
import re
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

JUNK_DOMAINS = {
    "example.com",
    "freightnet.com",
    "wcaworld.com",
    "sentry.io",
    "wix.com",
    "squarespace.com",
    "wordpress.com",
    "godaddy.com",
    "w3.org",
    "schema.org",
    "google.com",
    "facebook.com",
    "linkedin.com",
    "twitter.com",
    "instagram.com",
    "youtube.com",
    "gstatic.com",
    "googleapis.com",
}

JUNK_KEYWORDS = [
    "noreply",
    "no-reply",
    "donotreply",
    "support@",
    "info@freightnet",
    "spam",
    "abuse",
    "privacy",
    "webmaster",
    "postmaster",
]

_robots_cache: dict[str, RobotFileParser | None] = {}

_BLACKLIST_RAW = [
    "a.g.l mauritania sarl","a.g.l gambia limited",
    "aahil shipping & logistics pvt. ltd.",
    "abipa logistics",
    "able freight services llc",
    "accent maritime and aviation logistics l.l.c",
    "adatra s.a.r.l",
    "afg logistics pvt. ltd.",
    "afs logistics international pvt ltd","afs logistics international pvt. ltd.",
    "agl global logistic s.a.",
    "aires transportation & logistics services co., ltd.",
    "al hobail group",
    "al mulla logistics w.l.l.",
    "al- hidaih national ent l.l.c",
    "all lines logistics sp. z o.o.",
    "all lines shipping",
    "all-ways logistics india pvt. ltd.",
    "allcargotransport s.a.",
    "altisa",
    "america global logistics aka almacenes generales del istmo sa",
    "american transportation & logistics (at&l) canada inc.",
    "ample shipping & logistic services",
    "anatim",
    "angel freight limited",
    "aocean global logistics (hong kong) limited",
    "aog international",
    "apelsin logistics inc",
    "aqua air logistics wll","aqua global logistics wll",
    "arabital shipping",
    "arc worldwide vn co., ltd.","arc worldwide freight forwarding inc.",
    "areks kargo uluslararasi tasimacilik nak. lojistik hiz. ve tic ltd. sti.",
    "around world shipping group w.l.l.",
    "arrow speed line (i) pvt. ltd.",
    "ascomint sas","ascomint sas-asesores en comercio internacional sas.",
    "asg logistik pvt. ltd.",
    "asl","asl mauritius",
    "asl worldwide freight & logistics",
    "at freight international",
    "atlantic overseas express peru s.a.c.",
    "atlantis global line lojistik hizmetleri sanayi ve ticaret ltd. sti.",
    "atlantis global line lojistik hiz. san. ve tic. ltd. sti.",
    "atlas konteyner tasimacilik hizmetleri ltd sti",
    "australian shipping services pty ltd",
    "avant garde logistics llc",
    "awesome network ltd.",
    "awli amber worldwide peru",
    "beauty wise international logistics (shenzhen) co., ltd.",
    "beijing seajets international forwarding co ltd.",
    "bemar aduanas y transportes, s.l.",
    "bestway logistic services (pvt.) limited",
    "biz logistics peru s.a.c.",
    "boltcargo india pvt ltd",
    "btb cargo (registered as beyond borders ltd.)",
    "bulko airfreight","bulko airfreight (m) sdn. bhd.",
    "c.c. shah & sons",
    "camel worldwide cargo llc",
    "can forwarding s. de r.l. de c.v.",
    "can regional",
    "capital one shipping & logistics llc",
    "caravel logistics (middle east) llc","caravel logistics pvt ltd",
    "cargo care shipping forwarding llc","cargo care shipping & forwarding llc",
    "cargo solutions limited",
    "cargocare turkey lojistik hizletleri ltd. sti.",
    "cargoing (ningbo) int'l logistics co., ltd",
    "china costam global logistics (xi'an) co., ltd.",
    "cns intertrans (shenzhen) co., ltd.",
    "colos logistics",
    "concorde express cargo l.l.c",
    "connect cargo","connect cargo brasil logistica e transporte internacional de cargas ltda",
    "consorzio fidelis",
    "continental global cargo sac",
    "corporacion lg, s.a.",
    "cosco shipping logistics & supply chain management (beijing) co., ltd.",
    "criteria + s.r.o.","criteria + s.r.o. ( d.b.a importagent)",
    "csw italia s.r.l.",
    "cts logistics group",
    "custom international cargo",
    "dahnay logistics pvt. ltd.","dahnay logistics llc",
    "dax shipping company",
    "delpa chile (group)","delpa europe",
    "delta express & logistics",
    "dimensions logistics services pvt. ltd.",
    "discovery forwarder s.l.",
    "dualtec cargo panama",
    "dynamic world cargo (uk) ltd",
    "e-cargo international group",
    "e-freight international co.",
    "e2e global lines (q) packers & movers w.l.l","e2e global lines (q) wll",
    "eaglespeed international logistics pvt. ltd","eaglespeed international logistics pvt. ltd.",
    "edge global shipping llc",
    "efa","efa international forwarding & foreign trade co ltd.",
    "express groupage services","egs global forwarding",
    "elbfair logistics gmbh",
    "emg spedition (pvt) ltd",
    "emstar logistics (l.l.c)",
    "enlace logistics group s.a. de c.v.",
    "enpire lukasz wojciechowski",
    "equatorial lines pvt ltd",
    "equivalent lines pvt. ltd.",
    "ets-logistics, eurasian transport solutions b.v.",
    "euroway international logistics gmbh",
    "ever trust global logistics co., ltd",
    "exceed supply chain solutions india pvt ltd",
    "excellence logistics est.",
    "exo transport sa de cv",
    "express air freight / skyline freight","express air freight (hk) ltd.",
    "express freight & logistics",
    "express logistic",
    "fcl uk limited","f.c.l. uk limited",
    "fash logistics private limited",
    "fast cfs cargo services ltd","fast cfs cargo services",
    "fast lines logistics company",
    "faster track logistics co. ltd.",
    "fastport co., ltd",
    "fcl transit",
    "fendale logistics ltd.","fendale cargo services llc",
    "fidepat international co., ltd.",
    "flex solutions for shipping and logistics co llc",
    "flying fresh air freight - ffaf cargo",
    "focus shipping agencies",
    "fora logistics ltd.",
    "forskip line sia",
    "free on board global logistics limited",
    "freelance logistics llc",
    "freight cargo services, inc.",
    "freight house",
    "freightcrate technologies pvt. ltd.",
    "freightex shipping l.l.c.",
    "frontier logistics international","frontier logistics international cargo services",
    "full reach international freight forwarding ltd.",
    "general logistics services spa.",
    "geoz global llc",
    "getting logistics done benelux b.v.",
    "gf services & solutions s.a. de c.v.",
    "global air compass ltd",
    "global freight logistics ltd.",
    "global star intl services",
    "global trans solutions logistics group",
    "globespan logistics (s) pte ltd",
    "inspired logistics company limited (subsidiary of globespan logistics (s) pte ltd)",
    "globex global logistics services sdn bhd",
    "glory international freight forwarder co., ltd.",
    "go forward freight",
    "goodrich maritime private limited",
    "grandworld logistics co., ltd.",
    "green link trading co., ltd.",
    "gtt istanbul lojistik hizmetleri ve dis ticaret ltd. sti.",
    "gtt istanbul lojistik hiz ve dis tic ltd. sti.",
    "guangzhou anchor logistics co., ltd.",
    "harbour marine shipping and logistics",
    "higoshipping supply chain management (shanghai) co., ltd.",
    "ibp cargo & construction wll","ibp cargo services llc",
    "imorex shipping services ltd",
    "impoexporta",
    "in motion logistics",
    "inclusive logistics, l.l.c.",
    "indy",
    "inter-fret consolidators dmcc","inter-fret consolidators turkey",
    "international courier service llc","international courier service warehouse sp. z o.o.",
    "international freight group (ifg)","international freight group",
    "international trade solutions",
    "intracarga, s.a.",
    "iq solution supply chain & distribution & international cargo w.l.l.",
    "itmc llc",
    "j&g freight forwarders c.a.",
    "jms global logistics (hk) limited",
    "joongwon gls., ltd",
    "k.l. logistics international",
    "kab logistic s.a.",
    "kappal logistics private limited",
    "kargo box company",
    "key international transport s.a.c.",
    "keylogistics s.a.s","key logistics group llc","klmex s de rl de cv",
    "kgl logistics",
    "kompass international shipping services l.l.c","kompass international shipping services llc",
    "la tunisienne de transport multi-modal",
    "land-air cargo",
    "lex global logistics pvt. ltd.",
    "lim cargo logistic s.a.c.",
    "lion global forwarding pty ltd",
    "lmc forwarders sa de cv",
    "logicare freight fzc",
    "loginex sp. z o.o.",
    "loginport s.a.",
    "logistic master, s. de r. l. de c.v.",
    "logistica atlas s.a.c.",
    "logistics hub",
    "satyam shipping (i) pvt ltd","m/s. satyam shipping india limited",
    "macsco logistics co., ltd.",
    "magno i.t.l","magno i.t.l (aka magno spa)",
    "mam clearance & forwarding agency","mam enterprise llc",
    "maqtab dar sahan barqa al khadamahth al tijariya (diverse freight service)",
    "maqtab dar sahan barqa al khadamahth al tijariya - diverse freight service",
    "marinetrans india pvt ltd","marinetrans india pvt. ltd. - south india",
    "mars logistique",
    "mars trading london ltd",
    "may international",
    "meethale logistics pvt ltd",
    "mepp overseas freight services sp. zo.o.",
    "mercator transport argentina s.a.","mercator transport uruguay sa",
    "mercator transport international inc.",
    "mfs shipping w.l.l",
    "mg cargo service - rolf genkel, sole proprietorship",
    "mission freight fzco",
    "mks smart log s.a. de c.v.",
    "moon freight services",
    "multiair gmbh (dba multiair air & sea)",
    "multiple solutions ltd.",
    "naijil hilal shipping & cargo llc","n h shipping llc",
    "nellen & quack","nellen & quack gmbh & co. kg",
    "neptun logistics services inc.",
    "nine dragon global logistics corp.",
    "ningbo jade glory international forwarding co., ltd","ningbo jade glory international forwarding co., ltd.",
    "noble shipping & logistics llc","noble shipping and logistics l.l.c",
    "noor pak logistics international",
    "north ocean company w.l.l",
    "o primo transporte eireli me",
    "o.c. lines (china) logistics ltd.","oc-lines usa, llc",
    "ocean pioneer peru sac",
    "on dot freight llc","on dot freight",
    "onwayy cargo pvt. ltd.",
    "optimus gtl international forwarders, lda",
    "outside the box logistics",
    "owl international",
    "p. freight international co., ltd",
    "p3 logistics pvt. ltd.","p3 freight logistics india (opc) pvt. ltd",
    "pacific glory international logistics corp.",
    "pactrans air & sea, inc.",
    "pamm logistics llc",
    "panlloyd logistics pvt. ltd.",
    "partner trade llc",
    "patil container lines pvt. ltd.",
    "perfect cargo movers private ltd.",
    "peru cargo line s.a.c.",
    "pfi - primum freight international",
    "pg international srls",
    "philex logistics (u) ltd.",
    "pinnacle logistics","pinnacle logistics (thailand) co., ltd.",
    "platinum logistics colombo (pvt.) ltd.",
    "pns inter freight forwarding and logistics services co.",
    "pny logistics tech company",
    "polar star logistics","polar star logistics llc",
    "polarys cargo spa.",
    "pontus freight india private limited",
    "premier logistics corporation",
    "premium worldwide co., ltd.",
    "primacosped d.o.o.",
    "ps international",
    "pt. abxpress indonesia",
    "pt. ananta transport indonesia",
    "pt. artha graha xpressindo dba pt. agx logistics indonesia","pt. artha graha xpressindo",
    "pt. bee logistics transworld",
    "pt. dewata freight international tbk","pt. dewata freight international",
    "pt. eximku logistik indonesia",
    "pt. mats internasional indonesia",
    "pt. surya indotama logistik",
    "qingdao perimeter global logistics co., ltd.",
    "qingdao shirun international freight forwarding agent co., ltd.",
    "ql logistics solutions s.l.",
    "r&r global",
    "wiz logtec solutions private limited","radar ventures private limited",
    "wiz logtec freight llc","wiz logtec solutions singapore pte limited",
    "relan global logistic",
    "reliable shipping services inc.",
    "ucl global peru s.a.c","rg log corp",
    "rocargo shipping",
    "rocky logistics l.l.c",
    "royal shipping agency",
    "royal uni international logistics (hk) ltd","royal uni logistics colombo (pvt) ltd",
    "ruihang international supply chain technology co., ltd.",
    "rwa logistics - transportes ltda",
    "s.a.r.l. international power logistics",
    "sado logistic services",
    "saraimx logistics pvt. ltd.",
    "satkar logistics pvt. ltd.",
    "sav logistics pvt ltd","sav logistics limited",
    "sea-to-sky logistics lines inc.",
    "seafair germany gmbh","seafair peru s.a.c.","seafair usa, llc",
    "seagull maritime agencies","seagull maritime agencies pvt. ltd.",
    "seagull s.a.",
    "sealand logistics llc",
    "searoute shipping & cargo llc.",
    "seasky private limited",
    "sec logistic s.a.s.",
    "senni logistics s.a. de c.v.",
    "seven seas lines",
    "sg logistics l.l.c.",
    "shanghai auho logistics co., ltd.",
    "shanghai easton international forwarding co., ltd","shanghai easton international forwarding co., ltd.",
    "shanghai everdo s&w international chemical logistics co., ltd.",
    "shanghai ever-do international logistics co., ltd.",
    "shanghai hamel supply chain technology co., ltd.",
    "shanghai shining international logistics co., ltd","shanghai shining international logistics co., ltd.",
    "shanghai zuodi supply chain co., ltd.",
    "shen da logistics (cambodia) ltd.",
    "shenzhen g.y.l international logistics co., ltd.",
    "shenzhen kingone international logistics co., ltd.",
    "shenzhen plinsko int'l logistics co., ltd.",
    "shenzhen plinsko int'l logistics co., ltd. ningbo branch",
    "shenzhen tx-freight co., ltd.",
    "sigma international logistics (shanghai) co., ltd.",
    "silvan air & sea sp. z o.o. s.k.a.",
    "skr supply chain management pvt. ltd.",
    "sky air freight (pty) ltd.",
    "sng logistics (shanghai) co., ltd.",
    "solomon zewdu shipping & freight forwarding agent",
    "spi freight limited",
    "stag logistices pvt. ltd.",
    "steady routes logistics",
    "suijjin shipping pvt. ltd.",
    "superterra shipping lines",
    "teksan tunisie",
    "tline solutions lda",
    "top group international (s.e.a.) pte. ltd.",
    "torpedo logistics services",
    "towergate cargo logistics limited",
    "trafco logistics (pvt.) ltd.",
    "transvision shipping pvt. ltd.","trans aero link cargo l.l.c","trans vision sea shipping lines agents llc",
    "transcargo logistics, c.a.",
    "transcoma logistics services","transcoma global logistics",
    "transconnex international ltd.",
    "transfreight corporation pvt ltd",
    "transglocal express freight pvt. ltd.",
    "transitex - transitos de extremadura, s.a.",
    "transol global forwarding pvt ltd",
    "transportadora intercontinental s.a. de c.v.",
    "transporte maritimo y logistica",
    "tranzgate one maldives pvt. ltd.",
    "trans world logistics , llc","tw logistics, llc",
    "ulg logistics ltd",
    "ultima international transportation logistics and foreign trade co., ltd",
    "unicon logistics india pvt. ltd.","unicon logistics services llc",
    "unimar logistics llc",
    "union cargo group",
    "united shipping and logistics",
    "united transport services corp. - uts","united transport services, corp.",
    "universal shipping agencies",
    "vanguard l.l.c.",
    "velocity logistics solutions",
    "vert comex usa corp.",
    "vision freight shipping & agencies",
    "vsail international logistics co., ltd.",
    "white feather freight and contracting services company",
    "wisdom global logistics co., ltd.",
    "wiz logtec india pvt ltd.",
    "world trans & logistics senegal sarl",
    "world transport international ltda.",
    "worldlinks logi services private limited",
    "worldwide cargo agency & logistics s de rl de cv",
    "worldwide logistic solutions sas",
    "worldwide transport spa",
    "worth cargo international transport co., ltd.",
    "york international for logistics and clearance services",
    "zee tee express co.",
]


def random_ua() -> str:
    return random.choice(USER_AGENTS)


def random_headers() -> dict[str, str]:
    ua = random_ua()
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }


def _domain_root(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _norm(name: str) -> str:
    n = str(name).lower().strip()
    n = re.sub(r"[.,'\"/\\()&-]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


BLACKLIST = {_norm(x) for x in _BLACKLIST_RAW}


def is_blacklisted(company_name: str) -> bool:
    return _norm(company_name) in BLACKLIST


def is_allowed(url: str, user_agent: str = "*") -> bool:
    domain = _domain_root(url)
    if not domain:
        return True

    if domain not in _robots_cache:
        rp = RobotFileParser()
        robots_url = f"{domain}/robots.txt"
        rp.set_url(robots_url)
        try:
            rp.read()
            _robots_cache[domain] = rp
        except Exception:
            logging.warning("Unable to read robots.txt for %s", domain)
            _robots_cache[domain] = None
            return True

    rp = _robots_cache[domain]
    if rp is None:
        return True

    try:
        return rp.can_fetch(user_agent, url)
    except Exception:
        logging.warning("robots.txt parse failure for %s", domain)
        return True


def get_crawl_delay(url: str, user_agent: str = "*") -> float | None:
    domain = _domain_root(url)
    if not domain:
        return None

    is_allowed(url, user_agent)
    rp = _robots_cache.get(domain)
    if rp is None:
        return None

    try:
        return rp.crawl_delay(user_agent)
    except Exception:
        return None


def _parse_retry_after(value: str | None, fallback: float) -> float:
    if not value:
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _soft_block_status(resp: requests.Response) -> str | None:
    if resp.status_code == 403:
        return "blocked"

    text = (resp.text or "").lower()[:5000]
    block_signals = [
        "captcha",
        "recaptcha",
        "hcaptcha",
        "challenge-platform",
        "access denied",
        "access blocked",
        "please verify you are a human",
        "cloudflare",
        "ray id",
        "checking your browser",
        "just a moment",
        "enable javascript and cookies",
        "unusual traffic from your computer",
        "bot detection",
        "are you a robot",
    ]
    matches = sum(1 for signal in block_signals if signal in text)
    if matches < 2:
        return None

    captcha_signals = {
        "captcha",
        "recaptcha",
        "hcaptcha",
        "please verify you are a human",
        "are you a robot",
    }
    if any(signal in text for signal in captcha_signals):
        return "captcha"
    return "blocked"


def is_soft_blocked(resp: requests.Response) -> bool:
    return _soft_block_status(resp) is not None


def _apply_proxy(session: requests.Session, proxy: dict[str, str] | None) -> None:
    session.proxies.clear()
    if proxy:
        session.proxies.update({"http": proxy["http"], "https": proxy["https"]})
        setattr(session, "_proxy_server", proxy["server"])
    else:
        setattr(session, "_proxy_server", "")


def load_proxies() -> list[dict[str, str]]:
    raw_items: list[str] = []
    env_value = os.getenv("SCRAPE_PROXIES", "").strip()
    if env_value:
        raw_items.extend(part.strip() for part in env_value.split(","))
    else:
        proxies_file = Path(__file__).resolve().parent / "proxies.txt"
        if proxies_file.exists():
            raw_items.extend(line.strip() for line in proxies_file.read_text(encoding="utf-8").splitlines())

    proxies: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_items:
        if not item or item.startswith("#") or item in seen:
            continue
        seen.add(item)
        proxies.append({"http": item, "https": item, "server": item})
    return proxies


def get_proxy_session(proxies: list[dict[str, str]] | None = None) -> requests.Session:
    session = requests.Session()
    session.headers.update(random_headers())
    _apply_proxy(session, random.choice(proxies) if proxies else None)
    return session


def rotate_proxy(session: requests.Session, proxies: list[dict[str, str]] | None = None) -> requests.Session:
    if not proxies:
        _apply_proxy(session, None)
        return session

    current = getattr(session, "_proxy_server", "")
    candidates = [proxy for proxy in proxies if proxy["server"] != current]
    chosen = random.choice(candidates or proxies)
    _apply_proxy(session, chosen)
    logging.info("Rotated proxy to %s", chosen["server"])
    return session


def safe_get(
    session: requests.Session,
    url: str,
    timeout: int = 10,
    max_retries: int = 3,
    base_delay: float = 2.0,
    respect_robots: bool = True,
    user_agent: str = "*",
    proxies: list[dict[str, str]] | None = None,
    stats: "ScrapeStats | None" = None,
    pre_waited: bool = False,
):
    if respect_robots and not is_allowed(url, user_agent):
        logging.warning("Blocked by robots.txt: %s", url)
        if stats:
            stats.record("disallowed")
        return None, "disallowed"

    if respect_robots and not pre_waited:
        crawl_delay = get_crawl_delay(url, user_agent)
        if crawl_delay and crawl_delay > base_delay:
            extra_wait = crawl_delay - base_delay
            logging.info("Respecting crawl delay %.1fs for %s", extra_wait, url)
            time.sleep(extra_wait)

    for attempt in range(max_retries):
        try:
            session.headers.update(random_headers())
            logging.info("GET %s (attempt %s/%s)%s", url, attempt + 1, max_retries, f" via {getattr(session, '_proxy_server', '')}" if getattr(session, "_proxy_server", "") else "")
            resp = session.get(url, timeout=timeout, allow_redirects=True)

            if resp.status_code == 429:
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"), base_delay * (2 ** attempt))
                wait = min(retry_after, 60)
                logging.warning("429 rate limited on %s, waiting %.1fs", url, wait)
                if stats:
                    stats.record_retry()
                rotate_proxy(session, proxies)
                time.sleep(wait)
                continue

            if resp.status_code in (500, 502, 503, 504):
                wait = min(base_delay * (2 ** attempt), 60)
                logging.warning("%s on %s, retry in %.1fs", resp.status_code, url, wait)
                if stats:
                    stats.record_retry()
                rotate_proxy(session, proxies)
                time.sleep(wait)
                continue

            block_status = _soft_block_status(resp)
            if block_status:
                logging.warning("Soft block detected on %s (%s)", url, block_status)
                if stats:
                    stats.record(block_status)
                rotate_proxy(session, proxies)
                return None, block_status

            logging.info("GET %s -> %s", url, resp.status_code)
            if stats:
                stats.record("ok")
            return resp, "ok"

        except (requests.ConnectionError, requests.Timeout) as exc:
            wait = min(base_delay * (2 ** attempt), 60)
            logging.warning("%s on %s, retry %s/%s in %.1fs", type(exc).__name__, url, attempt + 1, max_retries, wait)
            if stats:
                stats.record_retry()
            rotate_proxy(session, proxies)
            time.sleep(wait)
        except Exception:
            logging.exception("Unexpected error on %s", url)
            if stats:
                stats.record("error")
            return None, "error"

    if stats:
        stats.record("error")
    return None, "error"


class RateLimiter:
    """Per-domain rate limiter."""

    def __init__(self, default_delay: float = 2.0):
        self._last_request: dict[str, float] = {}
        self._default_delay = default_delay

    def wait(self, url: str) -> None:
        domain = urlparse(url).netloc
        if not domain:
            return

        now = time.time()
        last = self._last_request.get(domain, 0.0)
        elapsed = now - last
        crawl_delay = get_crawl_delay(url) or 0.0
        delay = max(self._default_delay, crawl_delay)

        if elapsed < delay:
            time.sleep(delay - elapsed)

        self._last_request[domain] = time.time()


def _normalize_domain(value: str) -> str:
    candidate = value.strip().lower()
    if "://" in candidate:
        candidate = urlparse(candidate).netloc.lower()
    candidate = candidate.split("/")[0]
    if candidate.startswith("www."):
        candidate = candidate[4:]
    return candidate


def _email_matches_domain(email: str, base_domain: str) -> bool:
    domain = email.split("@", 1)[-1].lower()
    return domain == base_domain or domain.endswith(f".{base_domain}") or base_domain.endswith(f".{domain}")


def extract_emails(html: str, base_domain: str = "") -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    found: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if href.lower().startswith("mailto:"):
            email = href[7:].split("?")[0].strip().lower()
            if email:
                found.add(email)

    text = soup.get_text(separator=" ")
    for match in EMAIL_REGEX.findall(text):
        found.add(match.lower())

    cleaned: list[str] = []
    for email in sorted(found):
        email = email.strip(" <>[](){}.,;:'\"")
        if "@" not in email:
            continue
        domain = email.split("@", 1)[-1].lower()
        if len(email) > 120 or "." not in domain:
            continue
        if domain in JUNK_DOMAINS or any(domain.endswith(f".{junk}") for junk in JUNK_DOMAINS):
            continue
        if any(keyword in email for keyword in JUNK_KEYWORDS):
            continue
        if email not in cleaned:
            cleaned.append(email)

    if not base_domain:
        return cleaned

    normalized = _normalize_domain(base_domain)
    preferred = [email for email in cleaned if _email_matches_domain(email, normalized)]
    others = [email for email in cleaned if email not in preferred]
    return preferred + others


class ScrapeStats:
    """Track scraping outcomes for logging and monitoring."""

    def __init__(self) -> None:
        self.total = 0
        self.success = 0
        self.blocked = 0
        self.robots_denied = 0
        self.captcha = 0
        self.errors = 0
        self.retries = 0
        self.start_time = time.time()

    def record(self, status: str) -> None:
        self.total += 1
        if status == "ok":
            self.success += 1
        elif status == "disallowed":
            self.robots_denied += 1
        elif status == "captcha":
            self.blocked += 1
            self.captcha += 1
        elif status == "blocked":
            self.blocked += 1
        else:
            self.errors += 1

    def record_retry(self, count: int = 1) -> None:
        self.retries += count

    def summary(self) -> dict[str, float]:
        elapsed = time.time() - self.start_time
        return {
            "total": self.total,
            "success": self.success,
            "blocked": self.blocked,
            "robots_denied": self.robots_denied,
            "captcha": self.captcha,
            "errors": self.errors,
            "retries": self.retries,
            "elapsed_seconds": round(elapsed, 2),
            "success_rate": round((self.success / self.total * 100.0) if self.total else 0.0, 2),
        }

    def print_summary(self) -> None:
        summary = self.summary()
        print(f"  Requests made : {summary['total']}")
        print(f"  Request ok    : {summary['success']}")
        print(f"  Blocked       : {summary['blocked']}")
        print(f"  Robots denied : {summary['robots_denied']}")
        print(f"  Captcha       : {summary['captcha']}")
        print(f"  Errors        : {summary['errors']}")
        print(f"  Retries       : {summary['retries']}")
        print(f"  Elapsed sec   : {summary['elapsed_seconds']}")
