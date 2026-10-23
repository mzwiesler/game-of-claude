"""Security scan: what reached Claude, what Claude did, and how much could go wrong.

    python3 security.py                   # scan the last 7 days, save the report, print the findings
    python3 security.py --days 14 --json  # print the whole report as JSON
    python3 security.py --no-save         # print only, keep the saved report as it is

Three groups of checks over the transcripts (~/.claude/projects/**/*.jsonl) and the settings files:
leaks (secrets, credential files, files outside the project, personal data in prompts, tool inputs
and tool outputs), events (sandbox escapes and blocks, risky commands, actions in your name,
prompt-injection exposure, permission mode) and posture (sandbox, permission rules, plugins, MCP
servers, hooks). Only real tool_use / tool_result / prompt content counts: the system prompt and
tool descriptions in the transcripts quote the sandbox texts and must not produce hits.

The report never holds a full secret (first 4 + last 2 characters, length and kind), nothing is
sent anywhere, and server.py --export leaves it out. Reports go to
$XDG_DATA_HOME/claude-telemetry/security/<date>.json and latest.json (next to the XP ledger),
acknowledged findings to security/acks.json; the dashboard shows them in its Security card.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import ledger
from collect import CLAUDE_DIR, PROJECTS_DIR, _ts
from insights import _cmd_key, _repo_root, _text, read_settings, top

DIR = ledger.PATH.parent / "security"
KEY_PATH = DIR / ".key"  # per-install HMAC key for fingerprints (mode 600, made on first use)
KEEP = 60  # dated reports kept
DAYS = 7  # default look-back window
MANAGED = Path("/etc/claude-code/managed-settings.json")
HOME = str(Path.home())

# Writes to these count as production (MCP server names, Terraform workspaces); matched as words
PROD = ("prod", "prd", "production")
PROD_RE = re.compile(r"(?<![a-z])(" + "|".join(PROD) + r")(?![a-z])", re.I)
# Plugin marketplaces that are official; your own (e.g. the company's) go in config.json "trustedMarketplaces"
TRUSTED_MARKETPLACES = ("claude-plugins-official", "builtin")
CONFIG = Path(__file__).resolve().parent / "config.json"  # local and gitignored, see config.example.json
# Blocked hosts that are package registries or Claude Code's own endpoints: low, not medium
KNOWN_HOSTS = ("pypi.org", "files.pythonhosted.org", "registry.npmjs.org", "registry.yarnpkg.com", "registry.terraform.io",
               "releases.hashicorp.com", "checkpoint-api.hashicorp.com", "proxy.golang.org", "sum.golang.org", "crates.io",
               "static.crates.io", "index.crates.io", "repo.maven.apache.org", "repo1.maven.org", "api.nuget.org",
               "rubygems.org", "deb.debian.org", "security.debian.org", "archive.ubuntu.com", "security.ubuntu.com",
               "objects.githubusercontent.com", "api.anthropic.com", "statsig.anthropic.com", "*.datadoghq.com", "*.sentry.io")
# Allowed domains anyone can upload to: a way out for data
UPLOAD_HOSTS = ("github.com", "*.github.com", "gist.github.com", "*.githubusercontent.com", "pastebin.com", "*.pastebin.com",
                "paste.ee", "hastebin.com", "transfer.sh", "file.io", "0x0.st", "*.ngrok.io", "*.ngrok-free.app", "webhook.site")

# ---------- patterns ----------

# Secrets: (kind, severity, pattern); the value is group "v" when the pattern has one
SECRETS = (
    ("Anthropic API key", "high", r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    ("OpenAI-style key", "high", r"\bsk-(?!ant-)(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}"),
    ("GitHub token", "high", r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{50,}"),
    ("AWS access key", "high", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("Azure storage key", "high", r"AccountKey=(?P<v>[A-Za-z0-9+/]{40,}={0,2})"),
    ("Azure SAS signature", "high", r"[?&]sig=(?P<v>[A-Za-z0-9%+/]{30,}(?:%3D|=){0,2})"),
    ("Connection string password", "high", r"(?i)(?:^|[;\s\"'])(?:password|pwd)=(?P<v>[^;\s\"'<>{}$]{6,})"),
    ("Private key", "high", r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY(?: BLOCK)?-----\s*(?:[\w-]+: [^\n]*\n\s*)*(?P<v>[A-Za-z0-9+/=\s\\n]{64,})"),
    ("Password in a URL", "high", r"\b[a-z][a-z0-9+.-]{1,20}://[^/\s:@'\"]+:(?P<v>[^@\s/'\"]{4,})@[\w.-]+"),
    ("GitLab token", "high", r"\bglpat-[A-Za-z0-9_-]{20,}"),
    ("Azure DevOps PAT", "high", r"\b[A-Za-z0-9]{76}AZDO[A-Za-z0-9]{4}\b"),
    ("JWT", "high", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{20,}"),
    ("Slack token", "high", r"\bxox[bpas]-[A-Za-z0-9-]{20,}"),
    ("Atlassian API token", "high", r"\bATATT[A-Za-z0-9_=-]{30,}"),
    ("Databricks token", "high", r"\bdapi[0-9a-f]{32}(?:-\d)?\b"),
    ("Terraform Cloud token", "high", r"\b[A-Za-z0-9]{14}\.atlasv1\.[A-Za-z0-9_-]{60,}"),
    # lower confidence: a key word with something password-like after it
    ("Possible password / token", "medium",
     r"(?i)(?<![A-Za-z0-9])[A-Za-z0-9_]{0,40}?(?:password|passwd|secret|token|api[_-]?key)[A-Za-z0-9_]{0,20}[\"']?\s*[:=]\s*[\"']?"
     r"(?P<v>[^\s\"'`,;(){}\[\]<>]{8,})"),
)
SECRET_RE = [(k, sev, re.compile(p)) for k, sev, p in SECRETS]
PLACEHOLDER_WHOLE = re.compile(r"(.)\1{7,}|<[^>]*>|\$\{|^\$\w+$|changeme|example|placeholder|dummy|redacted|your[_-]|"
                               r"\.\.\.|…|^(?:pass(?:word)?|secret|pwd|token|x+|\*+)$", re.I)
PLACEHOLDER = re.compile(r"x{3,}|\*{3,}|<[^>]*>|\$\{|^\$|changeme|example|placeholder|dummy|redacted|your[_-]|fake|sample|\.\.\.|…", re.I)
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")
CARD = re.compile(r"(?<![\d.-])(?:4\d{3}|5[1-5]\d\d|2[2-7]\d\d|3[47]\d\d)(?:[ -]?\d{4}){2}[ -]?\d{3,4}(?![\d.-])")
IBAN_LEN = dict(AD=24, AE=23, AL=28, AT=20, AZ=28, BA=20, BE=16, BG=22, BH=22, BR=29, BY=28, CH=21, CR=22, CY=28, CZ=24,
                DE=22, DK=18, DO=28, EE=20, EG=29, ES=24, FI=18, FO=18, FR=27, GB=22, GE=22, GI=23, GL=18, GR=27, GT=28,
                HR=21, HU=28, IE=22, IL=23, IQ=23, IS=26, IT=27, JO=30, KW=30, KZ=20, LB=28, LC=32, LI=21, LT=20, LU=20,
                LV=21, MC=27, MD=24, ME=22, MK=19, MR=27, MT=31, MU=30, NL=18, NO=15, PK=24, PL=28, PS=29, PT=25, QA=29,
                RO=24, RS=22, SA=24, SC=31, SE=24, SI=19, SK=24, SM=27, ST=25, SV=28, TL=23, TN=24, TR=26, UA=29, VA=22,
                VG=24, XK=20)
EXAMPLE_IBANS = {"DE89370400440532013000", "GB82WEST12345698765432", "GB29NWBK60161331926819"}  # the documentation examples
TEST_CARDS = {"4111111111111111", "4242424242424242", "5555555555554444", "5105105105105100", "4012888888881881",
              "378282246310005", "371449635398431", "4000056655665556", "2223003122003222"}

# Credentials in commands that no secret pattern knows: (name part kept, value hidden)
NV = r"(?!\[)([^\s'\"&;|,}]+)"  # a value, unless it is already a mask
HIDE = [re.compile(p, re.I) for p in (
    r"(\b[a-z][\w+.-]*://[^/\s:@'\"]+:)(?!\[)([^@\s/'\"]+)(?=@)",  # URL userinfo
    r"(\bauthorization\s*[:=]\s*(?:bearer|basic|token|bot|digest)?\s*)" + NV,
    r"(\b(?:bearer|basic)\s+)(?!\[)([A-Za-z0-9._~+/=-]{6,})",
    r"((?:^|\s)(?:-u|--user)(?:\s+|=)['\"]?[^\s:'\"]+:)" + NV,  # curl -u user:pw
    r"(\b(?:mysql\w*|mariadb\w*)\b[^|;&\n]*?\s-p)" + NV,  # mysql -pS3cret
    r"(--pass(?:word)?(?:\s+|=)['\"]?)" + NV,
    r"(\bsshpass\s+-p\s*['\"]?)" + NV,
    r"(\b\w*(?:password|passwd|pwd|token|secret|key)\w*\s*=\s*['\"]?)" + NV,  # DB_PASSWORD=…, --api-key=…
    r"(\"\w*(?:password|passwd|token|secret|key)\w*\"\s*:\s*\")([^\"]+)",  # {"dbPassword": "…"}
)]

# Credential stores Claude should never see: (label, path pattern)
CRED = re.compile(r"""(?x)(?:^|[\s"'=:(])(?P<p>
    (?:~|\$HOME|/home/[\w.-]+|/root)/\.(?:ssh|aws|azure|gnupg)(?:/[^\s"'|;&)]*)?
  | (?:~|\$HOME|/home/[\w.-]+|/root)/\.kube/config\b
  | (?:~|\$HOME|/home/[\w.-]+|/root)/\.docker/config\.json
  | (?:~|\$HOME|/home/[\w.-]+|/root)/\.(?:netrc|git-credentials|pgpass)\b
  | (?:~|\$HOME|/home/[\w.-]+|/root)/\.config/gh/hosts\.yml
  | (?:~|\$HOME|/home/[\w.-]+|/root)/\.zshrc\.local\S*
  | [\w~$./-]*\bid_(?:rsa|ed25519|ecdsa|dsa)\b[\w.]*
  | [\w~$./-]*/[\w.-]+\.(?:pem|key|pfx|p12)\b
  | (?:[\w~$./-]*/)?\.env(?:\.(?!example|sample|template|dist)[\w-]+)?(?![\w./-])
  | /mnt/c/Users/[^/\s]+/AppData/\S*/Credentials\S*
  | \bcmdkey\b | \bGet-StoredCredential\b
)""")
READERS = re.compile(r"^(?:sudo\s+)?(?:cat|less|more|head|tail|grep|egrep|fgrep|rg|sed|awk|bat|strings|xxd|od|hexdump|jq|yq|"
                     r"base64|nl|tac|cut|sort|uniq|diff|type|Get-Content|gc)\b")
CERT_NAME = re.compile(r"(?:^|[/_.-])(?:ca|cert|certs|chain|fullchain|bundle|root|intermediate|trust\w*|public|pub)(?:[_.-]|$)", re.I)
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?(?:\n\s*\2[ \t]*(?=\n|$)|$)", re.S)
MESSAGE = re.compile(r"(?:\s-m|\s--message|\s--title|\s--body|\s-t|\s-b)\s*(?:\"(?:[^\"\\]|\\.)*\"|'[^']*')")
ENV_DUMP = re.compile(r"^\s*(?:env|printenv|set)\s*(?:\|\s*(?:sort|head|less|more|cat|tail)\b.*)?$")
DENIED = re.compile(r"Permission denied|Operation not permitted|EACCES|denied by|was denied|blocked|No such file", re.I)
# Directories that are never "outside the project": system, toolchains, caches
SYSTEM_DIRS = ("/usr/", "/opt/", "/etc/", "/lib", "/proc/", "/sys/", "/snap/", "/var/lib/", "/bin/", "/sbin/", "/dev/")
TOOL_PARTS = ("/site-packages/", "/node_modules/", "/.venv/", "/.cache/", "/.local/lib/", "/.local/share/", "/.npm/",
              "/.nvm/", "/.cargo/", "/.rustup/", "/go/pkg/", "/.terraform.d/", "/.terraform/")

# Risky commands (check 7): (label, pattern over a Bash command)
SEG = r"[^|;&\n]*"
TF_APPLY = rf"\bterraform\b{SEG}\s(?:apply|destroy)\b"
RISKY = (
    ("curl | sh", rf"\b(?:curl|wget)\b{SEG}\|\s*(?:sudo\s+)?(?:ba|z)?sh\b"),
    ("sudo", r"(?:^|[;&|]\s*|\n\s*)sudo\s"),
    ("rm -rf on an absolute or home path", r"\brm\s+-(?:[a-zA-Z]*r[a-zA-Z]*f|[a-zA-Z]*f[a-zA-Z]*r)[a-zA-Z]*\s+(?:--\s+)?[\"']?(?:/(?!tmp/|var/tmp/|home/[^/\s]+/\.claude/jobs/)|~|\$HOME)"),
    ("chmod -R 777", r"\bchmod\s+(?:-R\s+0?777|0?777\s+-R)\b"),
    ("git push --force", rf"\bgit\b{SEG}\spush\b{SEG}(?:\s--force(?:-with-lease)?\b|\s-f\b|\s\+[\w/]+)"),
    ("git push to main/master", rf"\bgit\b{SEG}\spush\b{SEG}(?<![\w/-])(?:main|master)(?![\w/-])"),
    ("git reset --hard + push", r"\bgit\s+reset\s+--hard\b[\s\S]*\bgit\b[^|;&\n]*\spush\b"),
    ("history rewrite", r"\bgit\s+(?:filter-branch|filter-repo)\b|\bgit\s+rebase\s[^|;&\n]*--root\b"),
    ("terraform apply/destroy", TF_APPLY),
    ("kubectl delete/apply", rf"\bkubectl\b{SEG}\s(?:delete|apply)\b"),
    ("az … delete", rf"\baz\s{SEG}\bdelete\b"),
    ("DROP TABLE/DATABASE", r"(?i)\bdrop\s+(?:table|database|schema)\b"),
    ("scp / rsync to a remote", rf"(?:^|[;&|]\s*|\n\s*)scp\s|\brsync\b{SEG}\s[\w.-]+@[\w.-]+:|\brsync\b{SEG}\s[\w.-]+:[/~]"),
    ("curl upload", rf"\bcurl\b{SEG}(?:\s-T\s|\s--upload-file\b|--data(?:-binary|-raw|-urlencode)?[ =]@|\s-d\s*@|\s-F\s*\S+=@)"),
    ("gh gist create", r"\bgh\s+gist\s+create\b"),
    ("netcat", r"(?:^|[;&|]\s*|\n\s*)(?:nc|ncat|netcat)\s"),
    ("base64 | network", r"\bbase64\b[^;&\n]*\|\s*(?:curl|wget|nc)\b"),
)
RISKY_RE = [(label, re.compile(p)) for label, p in RISKY]
# Actions in your name (check 8) from Bash: (server, what, pattern)
ACTIONS = (
    ("git", "pushes", rf"\bgit\b{SEG}\spush\b"),
    ("gh", "PRs created", r"\bgh\s+pr\s+create\b"),
    ("gh", "PRs merged", r"\bgh\s+pr\s+merge\b"),
    ("gh", "PR comments/reviews", r"\bgh\s+pr\s+(?:comment|review)\b"),
    ("gh", "issues created", r"\bgh\s+issue\s+create\b"),
    ("gh", "issue comments", r"\bgh\s+issue\s+comment\b"),
)
ACTIONS_RE = [(srv, what, re.compile(p)) for srv, what, p in ACTIONS]
WRITE_VERBS = {"create", "update", "delete", "add", "transition", "send", "post", "upload", "comment", "merge", "apply",
               "run", "cancel", "edit", "remove", "assign", "link", "publish", "write", "set", "move", "batch"}
READ_VERBS = {"get", "list", "search", "read", "fetch", "download", "query", "describe", "show", "find", "check", "export",
              "view", "lookup", "count", "authenticate", "complete", "guide", "take", "wait", "evaluate"}
NETWORK = re.compile(r"\b(?:curl|wget|ssh|scp|rsync|nc|gh|az|aws|gcloud|terraform|kubectl|helm|databricks|pip3?\s+install|"
                     r"npm\s+(?:install|i|publish)|uv\s+(?:pip|sync|add)|docker\s+(?:pull|push|login))\b|\bgit\b[^|;&\n]*\s(?:push|pull|fetch|clone|ls-remote)\b|https?://")
WRITE_TO = re.compile(r"(?:>>?|\btee\s+(?:-a\s+)?|\b(?:cp|mv|mkdir|rm|touch|chmod|ln)\s+(?:-\w+\s+)*)[\"']?((?:/|~/|\$HOME/)[\w.-][^\s\"';|&)]*)")
VIOL_LINE = re.compile(r"^\s*deny\s+(network-outbound|file-\w+|[\w-]+)\s+(\S+)", re.M)
SANDBOX_BLOCK = re.compile(r"(?:^|\n)<sandbox_violations>\s*\n(.*?)</sandbox_violations>", re.S)
# Sandbox escapes are grouped by what the command could do (check 5), most serious first
ESCAPES = (("excluded", "Excluded commands ran on the Windows host, with no sandbox"),
           ("write", "Commands wrote outside the project without the sandbox"),
           ("network", "Commands with network access ran outside the sandbox"),
           ("other", "Commands ran outside the sandbox"))
TEST_HOST = re.compile(r"(?:^|\.)(?:example(?:\.com|\.net|\.org)?|test|invalid|localhost)$")  # RFC 2606: never a real target
INJECT_WINDOW = 10  # tool calls after untrusted content in which an outward action counts (check 9)
RERUN_WINDOW = 5  # tool calls after a sandbox block in which an unsandboxed re-run counts (check 5)


def trusted_marketplaces(path: Path | None = None) -> tuple[str, ...]:
    """The official marketplaces plus config.json "trustedMarketplaces" (missing or broken file: none)."""
    try:
        extra = json.loads((path or CONFIG).read_text(encoding="utf-8")).get("trustedMarketplaces") or []
    except (OSError, ValueError, AttributeError):
        extra = []
    return TRUSTED_MARKETPLACES + tuple(m for m in extra if isinstance(m, str) and m not in TRUSTED_MARKETPLACES)


_keys: dict[Path, bytes] = {}


def _key() -> bytes:
    """Random per-install key (KEY_PATH, mode 600, made on first use): fingerprints of short secrets
    and card numbers cannot be brute-forced from the report, the acks or the page. If it cannot be
    written, a per-process key (fingerprints then change between runs, acks do not stick)."""
    p = KEY_PATH
    if p not in _keys:
        try:
            _keys[p] = p.read_bytes()
        except OSError:
            k = secrets.token_bytes(32)
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                with os.fdopen(os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
                    f.write(k)
            except FileExistsError:
                k = p.read_bytes()
            except OSError:
                pass
            _keys[p] = k
    return _keys[p]


def _h(v: str) -> str:
    return hmac.new(_key(), v.encode(), hashlib.sha256).hexdigest()[:12]


def mask(v: str, kind: str = "") -> str:
    """First 4 and last 2 characters plus length for long secrets; length only for short ones and
    IBANs, last 2 digits for card numbers: enough to recognise, useless to anyone else."""
    v = v.strip()
    if kind == "Card number":
        return f"…{v[-2:]} ({len(v)} digits)"
    if kind == "IBAN" or len(v) < 20:
        return f"({len(v)} chars)"
    return f"{v[:4]}…{v[-2:]} ({len(v)} chars)"


def _plausible(kind: str, v: str) -> bool:
    if len(set(v)) < 6:
        return False
    if kind != "Possible password / token":
        if PLACEHOLDER_WHOLE.search(v):
            return False
    elif PLACEHOLDER.search(v):
        return False
    else:
        classes = sum(bool(re.search(p, v)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
        # identifiers, paths, URLs and code (`token=self.get()`) are not passwords
        if re.search(r"(?:password|passwd|secret|token|key)s?$", v, re.I):
            return False
        if classes < 3 or not re.search(r"\d", v) or re.search(r"^(?:/|\.|https?:|true|false|null|none)|\.\w+\(|::|->|=>", v, re.I):
            return False
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", v) and not re.search(r"\d.*[A-Za-z]|[A-Za-z].*\d", v):
            return False
    if kind == "Password in a URL" and re.search(r"^\$|^\{|^%", v):
        return False
    if kind in ("OpenAI-style key", "Atlassian API token", "Slack token") and not re.search(r"\d", v):
        return False
    return True


def secrets_in(text: str):
    """(kind, severity, value) for each plausible secret in the text; a value two patterns match
    (or one inside another) counts once, under the more specific pattern (listed first)."""
    seen = []
    for kind, sev, rx in SECRET_RE:
        for m in rx.finditer(text):
            v = m.group("v") if "v" in rx.groupindex else m.group(0)
            if kind == "Private key":
                v = re.sub(r"\s|\\n", "", v)
            if _plausible(kind, v) and not any(v in x or x in v for x in seen):
                seen.append(v)
                yield kind, sev, v


def redact(text: str) -> str:
    """The text with every secret replaced by its masked form, for evidence that quotes commands."""
    def sub(m):
        v = m.group("v") if "v" in m.re.groupindex else m.group(0)
        return m.group(0).replace(v, f"[{mask(v)}]")
    for _, _, rx in SECRET_RE:
        text = rx.sub(sub, text)
    for rx in HIDE:  # passwords and tokens passed as arguments, headers, URL userinfo, VAR=…
        text = rx.sub(lambda m: m.group(1) + "[hidden]", text)
    return text


def _luhn(d: str) -> bool:
    s = 0
    for i, c in enumerate(reversed(d)):
        n = int(c) * (2 if i % 2 else 1)
        s += n - 9 if n > 9 else n
    return s % 10 == 0


def _iban_ok(v: str) -> bool:
    v = v.replace(" ", "")
    if IBAN_LEN.get(v[:2]) != len(v):
        return False
    n = "".join(str(int(c, 36)) for c in v[4:] + v[:4])
    return int(n) % 97 == 1


def pii_in(text: str):
    """(kind, value) for IBANs (mod-97 checked) and card numbers (Luhn checked, test numbers skipped)."""
    if any(c.isdigit() for c in text):
        for m in IBAN.finditer(text):
            if _iban_ok(m.group(0)) and m.group(0).replace(" ", "") not in EXAMPLE_IBANS:
                yield "IBAN", m.group(0).replace(" ", "")
        for m in CARD.finditer(text):
            d = re.sub(r"\D", "", m.group(0))
            if d not in TEST_CARDS and len(set(d)) >= 4 and _luhn(d):
                yield "Card number", d


def _shell(cmd: str) -> str:
    """A Bash command without heredoc bodies and quoted messages (commit, PR, issue texts), so
    text that is only written or quoted does not count as something the command does."""
    return MESSAGE.sub(" -m …", HEREDOC.sub(lambda m: f"<<{m.group(2)} …\n", cmd))


def _cred_path(p: str) -> bool:
    """A credential path worth reporting: not a certificate, not in a temp dir, not `$VAR/…`."""
    if p.startswith("$") and not p.startswith("$HOME") or "/tmp/" in p or p.startswith("/tmp") or "/.claude/jobs/" in p:
        return False
    name = p.rstrip("/").rpartition("/")[2]
    return not (re.search(r"\.(?:pem|key|p12|pfx)$", name) and CERT_NAME.search(name[:name.rfind(".")] or name))


def cred_reads(c: dict) -> set[str]:
    """Credential stores a call read: Read/Grep/Glob paths (Glob only lists names), and files a Bash command printed (cat, grep,
    head …; `source .env`, `--env-file`, `ls ~/.ssh` do not put the content into the context)."""
    if c["name"] in ("Read", "Grep", "Glob", "NotebookRead"):
        return {m.group("p") for p in c.get("paths") or [] for m in CRED.finditer(" " + p) if _cred_path(m.group("p"))}
    if c["name"] != "Bash":
        return set()
    cmd, found = _shell(c["cmd"]), set()
    for part in re.split(r"\s*(?:&&|\|\||;|\n)\s*", cmd):
        if ENV_DUMP.match(part):
            found.add("environment dump (env / printenv / set)")
        for seg in part.split("|"):
            seg = re.sub(r"^\s*(?:[A-Za-z_]\w*=\S*\s+)*", "", seg)
            if READERS.match(seg):
                found |= {m.group("p") for m in CRED.finditer(" " + seg) if _cred_path(m.group("p"))}
    return found


def _excluded(cmd: str, patterns) -> bool:
    """A command matching a `sandbox.excludedCommands` entry (`powershell.exe *` → `powershell.exe` as a word)."""
    cmd = cmd.strip()
    for e in patterns:
        pre = str(e or "").strip().rstrip(" *")
        if pre and re.match(re.escape(pre) + r"(?:\s|$)", cmd):
            return True
    return False


def _host(url: str) -> str:
    try:
        return urlparse(url if "//" in url else "//" + url).hostname or url[:60]
    except ValueError:
        return url[:60]


def _strings(v, out: list) -> list:
    """All string values of a tool input, nested."""
    if isinstance(v, str):
        out.append(v)
    elif isinstance(v, dict):
        for x in v.values():
            _strings(x, out)
    elif isinstance(v, list):
        for x in v:
            _strings(x, out)
    return out


# ---------- reading ----------

def scan(root: Path, since: datetime) -> list[dict]:
    """One summary per transcript with records since `since`: its tool calls (with the approval,
    sandbox and result facts security needs) and the secrets and personal data seen in prompts,
    tool inputs and tool outputs. Only files modified in the window are read."""
    out = []
    cutoff = since.timestamp()
    for path in root.glob("**/*.jsonl"):
        try:
            if path.stat().st_mtime < cutoff:
                continue
            lines = path.read_bytes().splitlines()
        except OSError:
            continue
        s = {"id": path.stem, "sid": None, "subagent": "subagents" in path.parts, "cwd": None, "start": None, "end": None,
             "modes": Counter(), "prompts": 0, "calls": [], "hits": [], "_calls": {}}
        for line in lines:
            if b'"type":"api-request' in line or b'"type":"attachment"' in line and not any(t in line for t in ATTACH_B):
                continue  # request copies and injected context (system prompt, tool docs): never evidence
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            ts = _ts(rec.get("timestamp"))
            if ts and ts < since:
                continue
            _record(s, rec, ts)
        s.pop("_calls")
        if s["start"]:
            s["sid"] = s["sid"] or s["id"]
            out.append(s)
    return out


# Attachments that carry content the user (or a hook) put into the context: type → (channel, field)
ATTACH = {"queued_command": ("prompt", "prompt"), "file": ("attached file", "content"),
          "edited_text_file": ("attached file", "snippet"), "hook_additional_context": ("hook context", "content")}
ATTACH_B = tuple(f'"type":"{t}"'.encode() for t in ATTACH)


def _hits(s: dict, text: str, channel: str, at: datetime | None) -> None:
    if not text or len(text) < 8:
        return
    for kind, sev, v in secrets_in(text):
        s["hits"].append({"type": "secret", "kind": kind, "severity": sev, "h": _h(v), "masked": mask(v, kind), "channel": channel, "at": at})
    for kind, v in pii_in(text):
        s["hits"].append({"type": "pii", "kind": kind, "severity": "medium", "h": _h(v), "masked": mask(v, kind), "channel": channel, "at": at})


def _record(s: dict, rec: dict, ts: datetime | None) -> None:
    typ = rec.get("type")
    if rec.get("permissionMode") and typ in ("user", "permission-mode"):
        s["modes"][rec["permissionMode"]] += 1
    if typ == "attachment":  # only the content-carrying kinds (ATTACH); sandbox/skill/tool docs are skipped
        a = rec.get("attachment") or {}
        channel, field = ATTACH.get(a.get("type"), (None, None))
        if channel:
            _hits(s, "\n".join(_strings(a.get(field), [])), channel, ts)
        return
    if typ not in ("user", "assistant") or rec.get("isCompactSummary"):
        return
    if ts:
        s["start"] = min(s["start"] or ts, ts)
        s["end"] = max(s["end"] or ts, ts)
    s["cwd"] = s["cwd"] or rec.get("cwd")
    s["sid"] = s["sid"] or rec.get("sessionId")
    content = (rec.get("message") or {}).get("content")
    if typ == "assistant":
        for b in content if isinstance(content, list) else []:
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            name, inp = b.get("name", "?"), b.get("input") or {}
            call = {"name": name, "at": ts, "cwd": rec.get("cwd") or s["cwd"], "decision": None, "rejected": False,
                    "error": False, "denied": False, "sandboxed": None, "violations": [], "result": False}
            if name == "Bash":
                call["cmd"] = inp.get("command", "")
                call["dds"] = bool(inp.get("dangerouslyDisableSandbox"))
            elif name in ("Read", "Grep", "Glob", "NotebookRead"):
                call["paths"] = [p for p in (inp.get("file_path"), inp.get("path"), inp.get("notebook_path")) if isinstance(p, str) and p]
                if name == "Glob" and isinstance(inp.get("pattern"), str) and inp["pattern"].startswith(("/", "~")):
                    call["paths"].append(inp["pattern"])
            elif name == "WebFetch":
                call["source"] = _host(str(inp.get("url", "")))
            elif name == "WebSearch":
                call["source"] = "web search"
            elif name.startswith("mcp__"):
                call["text"] = " ".join(_strings(inp, []))[:4000]  # for DROP TABLE and prod workspaces
                if name.endswith(("navigate_page", "new_page")) and inp.get("url"):
                    call["source"] = _host(str(inp["url"]))
                call["workspace"] = " ".join(str(v) for k, v in inp.items() if "workspace" in k.lower())
            s["_calls"][b.get("id")] = call
            s["calls"].append(call)
            _hits(s, "\n".join(_strings(inp, [])), f"{name} input", ts)
        return
    if isinstance(content, str) or not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content or []):
        if not rec.get("isMeta"):
            text = content if isinstance(content, str) else " ".join(
                b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")
            if text.strip():
                s["prompts"] += not rec.get("isSidechain") and not text.startswith("<")
                _hits(s, text, "subagent prompt" if rec.get("isSidechain") else "prompt", ts)
        return
    if not rec.get("isMeta"):  # text typed alongside tool results (interjections), minus injected reminders
        _hits(s, "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                           and not b.get("text", "").lstrip().startswith("<system-reminder>")), "prompt", ts)
    for b in content:
        if not isinstance(b, dict) or b.get("type") != "tool_result":
            continue
        call = s["_calls"].get(b.get("tool_use_id")) or {"name": "?", "at": ts, "cwd": s["cwd"], "violations": []}
        text = _text(b.get("content"))
        pd = rec.get("permissionDecision") or {}
        call.update(result=True, error=bool(b.get("is_error")), decision=(pd.get("source"), pd.get("reasonType")) if pd else None,
                    rejected=pd.get("decision") == "reject", denied=bool(b.get("is_error")) and bool(DENIED.search(text[:2000])))
        if "sandboxed" in rec:
            call["sandboxed"] = rec["sandboxed"]
            call["violations"] = [(v.get("kind", "?"), v.get("host") or v.get("path") or "?", v.get("port"))
                                  for v in rec.get("sandboxViolations") or [] if isinstance(v, dict)]
        elif call["name"] == "Bash":
            # older records: the sandbox's own block at the start of a line in the command's output
            m = SANDBOX_BLOCK.search(text)
            for kind, subj in VIOL_LINE.findall(m.group(1) if m else ""):
                kind = "network" if kind == "network-outbound" else kind
                host, _, port = subj.rpartition(":") if kind == "network" else (subj, "", "")
                call["violations"].append((kind, host or subj, int(port) if port.isdigit() else None))
        if call["name"] == "Bash" and "Operation not permitted" in text[:4000] and call.get("sandboxed") is not False:
            call["blocked"] = True
        _hits(s, text, f"{call['name']} output", ts)


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_all_settings(roots) -> dict:
    """{display path: settings} for the user settings, the managed settings and each repo root's
    .claude/settings.json, .claude/settings.local.json and .mcp.json (only files that exist)."""
    out = {"~/.claude/settings.json": read_settings()}
    m = _load(MANAGED)
    if m is not None:
        out[str(MANAGED)] = m
    for r in sorted(set(roots)):
        for rel in (".claude/settings.json", ".claude/settings.local.json", ".mcp.json"):
            d = _load(Path(r, rel))
            if d is not None:
                out[_short(str(Path(r, rel)))] = d
    return out


# ---------- analysis ----------

def finding(fid: str, kind: str, severity: str, title: str, evidence: str, fix: str, refs=(), group: str = "") -> dict:
    """insights.finding plus the sessions it happened in (newest 5 shown, all ids kept for the
    acknowledge rule) and the group (leaks / events / posture). `id` is the stable fingerprint."""
    refs = sorted({r["id"]: r for r in sorted(refs, key=lambda r: r["at"] or "")}.values(), key=lambda r: r["at"] or "", reverse=True)
    return {"id": fid, "fp": fid, "kind": kind, "group": group or kind, "severity": severity, "title": title,
            "evidence": evidence, "fix": fix, "sessions": refs[:5], "sessionIds": [r["id"] for r in refs][:300]}


def _short(p: str) -> str:
    return p.replace(HOME, "~", 1) if p.startswith(HOME) else p


def _ref(s: dict, at: datetime | None = None) -> dict:
    return {"id": s["sid"], "project": Path(_repo_root(s["cwd"] or "?")).name,
            "at": (at or s["start"]).isoformat(timespec="seconds") if (at or s["start"]) else None}


def _approver(call: dict) -> str:
    """Who let a tool call run: user (by hand), rule (allow rule), auto (classifier), mode, hook or unknown"""
    src, reason = call.get("decision") or (None, None)
    if src in ("user_temporary", "user_permanent"):
        return "user"
    if src == "config" and reason in ("rule", "subcommandResults"):
        return "rule"
    return {"classifier": "auto", "mode": "mode", "hook": "hook"}.get(reason, "unknown")


def _sev_by_approver(call: dict) -> str:
    """Who approved it matters: high only when you or an allow rule let it through."""
    if call.get("rejected"):
        return "medium"
    return "high" if _approver(call) in ("user", "rule") else "medium"


def _outside(p: str, root: str) -> str | None:
    """Top directory of an absolute path outside the repo root and the usual system/tool dirs, else None."""
    p = p.replace("$HOME", HOME, 1)
    if p.startswith("~"):
        p = HOME + p[1:]
    if not p.startswith("/"):
        return None
    p = p.rstrip("/") + "/"
    if (root and p.startswith(root.rstrip("/") + "/")) or p.startswith((str(CLAUDE_DIR) + "/", "/tmp/", "/var/tmp/")) \
            or p.startswith(SYSTEM_DIRS) or any(t in p for t in TOOL_PARTS):
        return None
    parts = p.strip("/").split("/")
    if p.startswith(HOME + "/"):
        n = len(Path(HOME).parts) - 1
        return "~/" + "/".join(parts[n:n + 2])
    if p.startswith("/mnt/c/Users/"):
        return "/" + "/".join(parts[:5])
    if p.startswith("/home/"):
        return "/" + "/".join(parts[:3])
    return "/" + "/".join(parts[:2])


SEV = {"high": 0, "medium": 1, "low": 2}


def analyze(sessions: list[dict], settings: dict, days: int, now: datetime) -> dict:
    """settings: {display path: settings dict} as read_all_settings returns it."""
    main = [s for s in sessions if not s["subagent"]]
    calls = [(s, c) for s in sessions for c in s["calls"]]
    bash = [(s, c) for s, c in calls if c["name"] == "Bash"]
    excluded = [e for d in settings.values() for e in ((d.get("sandbox") or {}).get("excludedCommands") or [])]
    F, passed = [], []

    # ----- A. leaks -----
    by = defaultdict(list)
    for s in sessions:
        for h in s["hits"]:
            by[h["h"]].append((s, h))
    leaks = pii = 0
    for hh, hits in sorted(by.items(), key=lambda kv: (SEV[kv[1][0][1]["severity"]], -len(kv[1]))):
        h = hits[0][1]
        ch = Counter(x["channel"] for _, x in hits)
        sess = {s["sid"] for s, _ in hits}
        refs = [_ref(s, x["at"]) for s, x in hits]
        if h["type"] == "secret":
            leaks += 1
            F.append(finding(f"secret:{hh}", "leak", h["severity"], f"{h['kind']} reached Claude",
                             f"{h['masked']} · {len(hits)}× in {len(sess)} session{'s' * (len(sess) > 1)} · {top(ch, 4)}",
                             "Rotate it now: it was sent to Anthropic with the conversation. Keep it where Claude cannot read it "
                             "(credential store, env var denied in `sandbox.credentials`)." if h["severity"] == "high" else
                             "Check whether this is a real credential; if it is, rotate it.", refs, "leaks"))
        else:
            pii += 1
            F.append(finding(f"pii:{hh}", "leak", "medium", f"{h['kind']} in the conversation",
                             f"{h['masked']} · {len(hits)}× in {len(sess)} session{'s' * (len(sess) > 1)} · {top(ch, 4)}",
                             "Check where it came from; keep real customer and personal data out of sessions (use masked test data).", refs, "leaks"))
    if not leaks:
        passed.append("No secrets in prompts, tool inputs or tool outputs")
    if not pii:
        passed.append("No IBANs or card numbers")

    # credential files and environment dumps
    cred = defaultdict(list)
    for s, c in calls:
        for p in cred_reads(c):
            cred[_short(p.replace("$HOME", "~"))].append((s, c))
    for p, hits in sorted(cred.items()):
        ok = [(s, c) for s, c in hits if c["result"] and not (c["error"] or c["rejected"] or c["denied"]) and c["name"] != "Glob"]
        listed = not ok and all(c["name"] == "Glob" for _, c in hits)
        F.append(finding(f"cred:{p}", "leak", "high" if ok else "medium",
                         f"Credential file read: {redact(p)}" if ok else f"Credential location listed: {redact(p)}" if listed
                         else f"Credential file access blocked: {redact(p)}",
                         f"{len(hits)}× ({len(ok)} succeeded) via {top(Counter(c['name'] for _, c in hits), 3)}"
                         + (f", e.g. `{redact(_shell(hits[0][1]['cmd']))[:140]}`" if hits[0][1]["name"] == "Bash" else ""),
                         "If it reached Claude, rotate what is in it. Deny it for good: `sandbox.filesystem.denyRead` / "
                         "`sandbox.credentials` (mode deny) plus a `Read(<path>)` deny rule.", [_ref(s, c["at"]) for s, c in hits], "leaks"))
    if not cred:
        passed.append("No credential files or environment dumps read")

    # files outside the project
    out_low, out_med = defaultdict(list), defaultdict(list)
    for s, c in calls:
        root = _repo_root(c.get("cwd") or s["cwd"] or "")
        for p in c.get("paths") or []:
            d = _outside(p, root)
            if d:
                (out_med if d.startswith(("/mnt/c/Users/", "/home/")) else out_low)[d].append((s, c))
    for d, hits in sorted(out_med.items()):
        F.append(finding(f"outside:{d}", "leak", "medium", f"Read files in {redact(d)}", f"{len(hits)} reads, e.g. {redact(_short(hits[0][1]['paths'][0]))[:120]}",
                         "Check these were meant to go to Claude; add the directory to `sandbox.filesystem.denyRead` if not.",
                         [_ref(s, c["at"]) for s, c in hits], "leaks"))
    if out_low:
        hits = [x for v in out_low.values() for x in v]
        F.append(finding("outside", "leak", "low", "Read files outside the session's project",
                         redact(top(Counter({d: len(v) for d, v in out_low.items()}), 6)),
                         "Usually other repos you pointed it at; fine if intended.", [_ref(s, c["at"]) for s, c in hits], "leaks"))

    # ----- B. events -----
    # sessions whose sandbox was off altogether (every Bash result says sandboxed: false, and not
    # only because of excluded commands)
    off = [s for s in sessions if any(c.get("sandboxed") is False and not _excluded(c["cmd"], excluded) for c in s["calls"] if c["name"] == "Bash")
           and not any(c.get("sandboxed") for c in s["calls"]) and not any(c.get("dds") for c in s["calls"])]
    off_ids = {id(s) for s in off}
    if off:
        projects = Counter(Path(_repo_root(s["cwd"] or "?")).name for s in off)
        F.append(finding("sandbox-off", "event", "medium", "Sessions ran without the sandbox",
                         f"{len(off)} sessions, every command unsandboxed: {top(projects, 4)}",
                         "Enable the sandbox for these projects (`sandbox.enabled: true`; check the repo's .claude/settings*.json).",
                         [_ref(s) for s in off], "events"))

    escapes = defaultdict(list)
    for s in sessions:
        last_block = {}
        for i, c in enumerate(s["calls"]):
            if c["name"] != "Bash":
                continue
            key = redact(_cmd_key(c["cmd"]))
            ex = _excluded(c["cmd"], excluded)
            ran = c["result"] and not c["rejected"]  # refused or never answered: nothing left the sandbox
            unsb = ran and (c.get("dds") or ex or (c.get("sandboxed") is False and id(s) not in off_ids))
            if unsb:
                c["rerun"] = i - last_block.get(key, -99) <= RERUN_WINDOW
                c["excluded"] = ex
                escapes[key].append((s, c))
            if c["violations"] or c.get("blocked"):
                last_block[key] = i
    cats, wrote = defaultdict(list), Counter()
    for key, hits in sorted(escapes.items(), key=lambda kv: -len(kv[1])):
        reruns = [(s, c) for s, c in hits if c["rerun"]]
        if reruns:
            sev = "high" if any(_sev_by_approver(c) == "high" for _, c in reruns) else "medium"
            F.append(finding(f"escape-rerun:{key}", "event", sev, f"Blocked by the sandbox, then re-run outside it: {key}",
                             f"{len(reruns)}× · approved by {top(Counter(_approver(c) for _, c in reruns), 3)} · e.g. `{redact(_shell(reruns[0][1]['cmd']))[:140]}`",
                             "Allow what the command needed in /sandbox instead of leaving it; check what it did outside.",
                             [_ref(s, c["at"]) for s, c in reruns], "events"))
        for s, c in hits:
            sh = _shell(c["cmd"])
            out = [d for m in WRITE_TO.finditer(sh) if (d := _outside(m.group(1), _repo_root(c.get("cwd") or s["cwd"] or "")))]
            wrote.update(out)
            cats["excluded" if c["excluded"] else "write" if out else "network" if NETWORK.search(sh) else "other"].append((s, c, key))
    for cat, title in ESCAPES:
        hits = cats.get(cat)
        if hits:
            F.append(finding(f"escape:{cat}", "event", "medium", title,
                             f"{len(hits)}×: {top(Counter(k for _, _, k in hits), 5)}" + (f" · wrote to {top(wrote, 3)}" if cat == "write" else "")
                             + f" · approved by {top(Counter(_approver(c) for _, c, _ in hits), 3)} · e.g. `{redact(_shell(hits[0][1]['cmd']))[:140]}`",
                             "Allow what they needed in /sandbox (domains, write paths) so they can stay inside; "
                             "`allowUnsandboxedCommands: false` closes the escape hatch.", [_ref(s, c["at"]) for s, c, _ in hits], "events"))
    if not escapes and not off:
        passed.append("No commands outside the sandbox")

    blocks = defaultdict(list)
    for s, c in calls:
        for kind, subj, port in c["violations"]:
            blocks[(kind, subj)].append((s, c, port))
    known = defaultdict(list)
    for (kind, subj), hits in sorted(blocks.items(), key=lambda kv: -len(kv[1])):
        if kind == "network" and not TEST_HOST.search(subj) and not any(fnmatch.fnmatch(subj, k) for k in KNOWN_HOSTS):
            F.append(finding(f"blocked:{subj}", "event", "medium", f"Sandbox blocked network access to {subj}",
                             f"{len(hits)}× by {top(Counter(_cmd_key(c.get('cmd', '')) for _, c, _ in hits), 3)}",
                             f"If {subj} is legitimate add it to `sandbox.network.allowedDomains`; otherwise look at what tried to reach it.",
                             [_ref(s, c["at"]) for s, c, _ in hits], "events"))
        else:
            known[f"{subj}" if kind == "network" else f"{kind} {subj}"].extend(hits)
    if known:
        F.append(finding("blocked", "event", "low", "Sandbox blocks (registries, Claude's own endpoints, test hosts, files)",
                         top(Counter({k: len(v) for k, v in known.items()}), 6),
                         "Nothing to do unless a tool kept failing on it.", [_ref(s, c["at"]) for v in known.values() for s, c, _ in v], "events"))

    # risky commands and actions in your name
    risky, acts, prod = defaultdict(list), defaultdict(Counter), defaultdict(list)
    act_refs = defaultdict(list)
    seq = {}  # (session, call index) of outward actions, for check 9
    for s in sessions:
        for i, c in enumerate(s["calls"]):
            labels = []
            if c["name"] == "Bash":
                sh = _shell(c["cmd"])
                labels = [label for label, rx in RISKY_RE if rx.search(sh)]
                if c["result"] and not (c["error"] or c["rejected"]):
                    for srv, what, rx in ACTIONS_RE:
                        if rx.search(sh):
                            acts[srv][what] += 1
                            act_refs[srv].append(_ref(s, c["at"]))
                            labels.append(f"{srv} {what}")
                if re.search(TF_APPLY, sh) and PROD_RE.search(sh) and c["result"] and not (c["error"] or c["rejected"]):
                    prod["terraform (Bash)"].append((s, c))
            elif c["name"].startswith("mcp__"):
                parts = c["name"].split("__")
                srv, tool = parts[1] if len(parts) > 2 else "?", parts[-1]
                if re.search(r"(?i)\bdrop\s+(?:table|database|schema)\b", c.get("text", "")):
                    labels.append("DROP TABLE/DATABASE")
                verb = next((w for w in re.split(r"[_\-]", tool.lower()) if w in WRITE_VERBS or w in READ_VERBS), None)
                if verb in WRITE_VERBS and c["result"] and not (c["error"] or c["rejected"]):
                    acts[srv][tool] += 1
                    act_refs[srv].append(_ref(s, c["at"]))
                    labels.append(f"{srv} {tool}")
                    if PROD_RE.search(srv) or PROD_RE.search(c.get("workspace", "")):
                        prod[srv].append((s, c))
            for label in labels:
                if label in dict(RISKY):
                    risky[label].append((s, c))
            if labels:
                seq[(id(s), i)] = labels[0]
    for label, hits in sorted(risky.items(), key=lambda kv: -len(kv[1])):
        sev = "high" if any(_sev_by_approver(c) == "high" for _, c in hits) else "medium"
        F.append(finding(f"risky:{label}", "event", sev, f"Risky command: {label}",
                         f"{len(hits)}× · approved by {top(Counter(_approver(c) if not c['rejected'] else 'blocked' for _, c in hits), 3)}"
                         f" · e.g. `{redact(_shell(hits[0][1].get('cmd') or hits[0][1]['name']))[:160]}`",
                         "Review the session; an `ask` rule (permissions.ask) for this command makes it always need your OK.",
                         [_ref(s, c["at"]) for s, c in hits], "events"))
    if not risky:
        passed.append("No risky commands (curl | sh, sudo, rm -rf /, force push, terraform apply, uploads …)")
    for srv, hits in sorted(prod.items()):
        F.append(finding(f"prod:{srv}", "event", "high", f"Write to a production target: {srv}",
                         f"{len(hits)}× · {top(Counter(redact(_shell(c.get('cmd', c['name'])))[:80] for _, c in hits), 3)}",
                         "Production changes should go through your change process; add an `ask` rule for this tool.",
                         [_ref(s, c["at"]) for s, c in hits], "events"))
    if not prod:
        passed.append("No writes to production targets")
    for srv, what in sorted(acts.items(), key=lambda kv: -sum(kv[1].values())):
        F.append(finding(f"actions:{srv}", "event", "low", f"Actions in your name: {srv}", top(what, 6),
                         "Inventory: check they were all intended.", act_refs[srv], "events"))

    # prompt-injection exposure: untrusted content, then an outward action within a few calls
    inj = defaultdict(list)
    for s in sessions:
        for i, c in enumerate(s["calls"]):
            src = c.get("source") or (next((p for p in c.get("paths") or [] if "/Downloads/" in p), None) and "a downloaded file")
            if not src:
                continue
            nxt = next((seq[(id(s), j)] for j in range(i + 1, min(i + 1 + INJECT_WINDOW, len(s["calls"]))) if (id(s), j) in seq), None)
            if nxt:
                inj[src].append((s, c, nxt))
    for src, hits in sorted(inj.items()):
        F.append(finding(f"inject:{src}", "event", "medium", f"Outward action after reading untrusted content from {src}",
                         f"{len(hits)}× · followed by {top(Counter(n for _, _, n in hits), 3)}",
                         "Check the action was what you asked for, not something the page told Claude to do.",
                         [_ref(s, c["at"]) for s, c, _ in hits], "events"))
    if not inj:
        passed.append("No outward actions right after web or download reads")

    # permission mode
    modes = Counter(m for s in main for m in s["modes"])
    bypass = [s for s in sessions if s["modes"].get("bypassPermissions")]
    if bypass:
        F.append(finding("mode:bypass", "event", "high", "Sessions ran in bypassPermissions mode", f"{len(bypass)} sessions",
                         "Do not bypass permissions on the company machine; use auto or default mode.", [_ref(s) for s in bypass], "events"))
    else:
        passed.append("No bypassPermissions sessions")
    if modes:
        F.append(finding("modes", "event", "low", "Permission modes used",
                         top(Counter({m: sum(1 for s in main if s["modes"].get(m)) for m in modes}), 5) + " sessions",
                         "Auto mode lets the classifier approve; the checks above show what it approved.", [], "events"))

    # ----- C. posture -----
    F += posture(settings, calls, passed)

    F.sort(key=lambda f: (SEV[f["severity"]], ["leaks", "events", "posture"].index(f["group"])))
    unsb = sum(len(v) for v in escapes.values())
    return {
        "generatedAt": now.isoformat(timespec="seconds"),
        "days": days,
        "since": (now - timedelta(days=days)).isoformat(timespec="seconds"),
        "stats": {
            "sessions": len(main), "subagents": len(sessions) - len(main), "prompts": sum(s["prompts"] for s in main),
            "toolCalls": len(calls), "bash": len(bash), "unsandboxed": unsb, "sandboxOff": len(off),
            "mcpWrites": sum(sum(v.values()) for k, v in acts.items() if k not in ("git", "gh")),
            "settingsFiles": sorted(settings),
            "high": sum(f["severity"] == "high" for f in F), "medium": sum(f["severity"] == "medium" for f in F),
            "low": sum(f["severity"] == "low" for f in F),
        },
        "findings": F,
        "passed": passed,
    }


def _rule_cmd(rule: str) -> str | None:
    """`Bash(curl:*)` → `curl`, `Bash` / `Bash(*)` → `*`, other tools → None."""
    m = re.fullmatch(r"Bash(?:\((.*)\))?", rule.strip())
    if not m:
        return None
    inner = (m.group(1) or "*").strip()
    return "*" if inner in ("*", ":*", "") else inner


def _rule_label(rule: str) -> str:
    """A Bash rule by its command word only (`Bash(curl …)`): rules can carry arguments with credentials."""
    c = _rule_cmd(rule)
    if c is None or c == "*":
        return redact(rule)
    w = re.split(r"[\s:]", c, maxsplit=1)[0]
    return f"Bash({w}{' …' if len(c) > len(w) else ''})"


def posture(settings: dict, calls: list, passed: list) -> list[dict]:
    F = []
    sb_enabled = [(src, (d.get("sandbox") or {}).get("enabled")) for src, d in settings.items() if isinstance(d.get("sandbox"), dict)]
    for src, d in settings.items():
        sb, perms = d.get("sandbox") or {}, d.get("permissions") or {}
        allow = [a for a in perms.get("allow") or [] if isinstance(a, str)]
        where = f"in {src}"
        if sb.get("enabled") is False:
            F.append(finding(f"posture:sandbox-off:{src}", "posture", "high", "Sandbox disabled", f"`sandbox.enabled: false` {where}",
                             "Set `sandbox.enabled: true`; allow what the project needs with /sandbox instead.", group="posture"))
        if sb.get("allowUnsandboxedCommands") is True:
            F.append(finding(f"posture:unsandboxed-allowed:{src}", "posture", "medium", "Escape hatch open: commands may leave the sandbox",
                             f"`sandbox.allowUnsandboxedCommands: true` {where}; in auto mode the classifier decides alone",
                             "Set it to false once the sandbox allows what you need (or keep it and watch the escapes above).", group="posture"))
        for e in sb.get("excludedCommands") or []:
            cmd = str(e or "").strip().rstrip(" *")
            if not cmd:
                continue
            in_allow = [a for a in allow if _rule_cmd(a) == "*" or re.match(re.escape(cmd) + r"(?:[\s:*]|$)", _rule_cmd(a) or "")]
            word = cmd.split()[0]
            F.append(finding(f"posture:excluded:{src}:{_h(cmd)}", "posture", "high" if in_allow else "medium",
                             f"Excluded from the sandbox: {word}{' …' if cmd != word else ''}",
                             f"`sandbox.excludedCommands` {where}: runs with no sandbox at all"
                             + (f", and allowed without asking ({', '.join(map(_rule_label, in_allow))})" if in_allow else ""),
                             "Remove the exclusion if you can; otherwise keep it out of `permissions.allow` so each run asks.", group="posture"))
        net = (sb.get("network") or {}).get("allowedDomains") or []
        if "*" in net:
            F.append(finding(f"posture:any-domain:{src}", "posture", "high", "Sandbox allows every domain", f"`*` in allowedDomains {where}",
                             "List the domains the projects need instead.", group="posture"))
        up = [h for h in net if h in UPLOAD_HOSTS]
        if up:
            F.append(finding(f"posture:upload-hosts:{_h(src + ','.join(sorted(up)))}", "posture", "low", "Allowed domains anyone can upload to",
                             f"{', '.join(up)} {where}: an exfil channel if Claude is misled", "Fine if needed for git; keep the list short.", group="posture"))
        wide = [w for w in (sb.get("filesystem") or {}).get("allowWrite") or [] if w.rstrip("/") in ("~", "", "$HOME", HOME, "/")]
        if wide:
            F.append(finding(f"posture:allow-write:{src}", "posture", "high", "Sandbox may write anywhere in home or root",
                             f"allowWrite {', '.join(wide)} {where}", "Allow specific directories (e.g. ~/.cache, ~/.azure) instead.", group="posture"))
        broad = [a for a in allow if (c := _rule_cmd(a)) is not None and (c == "*" or re.fullmatch(
            r"(?:python\d*(?:\.\d+)?|node|bash|sh|zsh|curl|wget|ssh|scp|powershell(?:\.exe)?|pwsh)(?:\s*(?::\*|\*|-|-c\s*:?\*?|-c\s.*\*))?", c))]
        if broad:
            F.append(finding(f"posture:broad-allow:{_h(src + ','.join(sorted(broad)))}", "posture", "medium", "Broad allow rules",
                             f"{', '.join(map(_rule_label, broad))} {where}: these run anything without asking",
                             "Narrow them to the exact commands (e.g. `Bash(python3 -m pytest:*)`).", group="posture"))
        mcpw = [a for a in allow if a.startswith("mcp__") and next(
            (w for w in re.split(r"[_\-]", a.split("__")[-1].lower()) if w in WRITE_VERBS or w in READ_VERBS), None) in WRITE_VERBS]
        if mcpw:
            F.append(finding(f"posture:mcp-write-allow:{_h(src + ','.join(sorted(mcpw)))}", "posture", "medium", "MCP write tools run without asking",
                             f"{', '.join(a.split('__')[-1] for a in mcpw)} {where}",
                             "Move them from `permissions.allow` to `ask` so each write in your name needs your OK.", group="posture"))
        whole = sorted({a.split("__")[1] for a in allow if a.startswith("mcp__") and (a.count("__") == 1 or a.endswith("__*"))})
        for srv in whole:
            F.append(finding(f"posture:mcp-all-allow:{src}:{srv}", "posture", "medium", f"All tools of {srv} run without asking, writes included",
                             f"`mcp__{srv}` allowed as a whole {where}",
                             "Allow the read tools by name and leave the write tools to ask.", group="posture"))
        if perms.get("defaultMode") == "bypassPermissions" or d.get("skipDangerousModePermissionPrompt") is True:
            F.append(finding(f"posture:bypass:{src}", "posture", "high", "Permission bypass configured",
                             f"`defaultMode: bypassPermissions` or `skipDangerousModePermissionPrompt` {where}",
                             "Remove it; use auto mode.", group="posture"))
        for event, groups in (d.get("hooks") or {}).items():
            for g in groups if isinstance(groups, list) else []:
                for hk in (g.get("hooks") or []) if isinstance(g, dict) else []:
                    cmd = str(hk.get("command", "")) if isinstance(hk, dict) else ""
                    if re.search(rf"\b(?:curl|wget)\b{SEG}\|\s*(?:ba|z)?sh\b|\bnpx\s+(?:-y\s+)?\S+@latest\b|\buvx\s", cmd):
                        F.append(finding(f"posture:hook:{_h(src + cmd)}", "posture", "medium", f"{event} hook runs code fetched from the internet",
                                         f"`{redact(cmd)[:140]}` {where}", "Pin the version or vendor the script.", group="posture"))

    # passed sandbox checks (over all files)
    if not any(e is False for _, e in sb_enabled) and any(e is True for _, e in sb_enabled):
        passed.append("Sandbox enabled")
    elif not any(e is not None for _, e in sb_enabled):
        F.append(finding("posture:sandbox-not-enabled", "posture", "high", "Sandbox not enabled",
                         "no settings file sets `sandbox.enabled: true`", "Enable it in ~/.claude/settings.json (/sandbox).", group="posture"))
    sbs = [d.get("sandbox") or {} for d in settings.values()]
    if any(any(isinstance(x, dict) and x.get("mode") == "deny" for v in (sb.get("credentials") or {}).values() if isinstance(v, list) for x in v) for sb in sbs):
        passed.append("Credentials denied in the sandbox (sandbox.credentials)")
    if any((sb.get("filesystem") or {}).get("denyRead") for sb in sbs):
        passed.append("sandbox.filesystem.denyRead set")
    deny = [a for d in settings.values() for a in (d.get("permissions") or {}).get("deny") or [] if isinstance(a, str)]
    if any(re.fullmatch(r"(Edit|Write)\(~?/?.*\.claude/settings(\.local)?\.json\)", a) for a in deny):
        passed.append("Claude may not edit its own settings (deny rule)")
    if not any(f["id"].startswith(("posture:broad-allow", "posture:mcp-write-allow", "posture:mcp-all-allow")) for f in F):
        passed.append("No broad allow rules")

    # extensions: plugins by marketplace, MCP servers seen in tool calls
    plugins = {k: v for d in settings.values() for k, v in (d.get("enabledPlugins") or {}).items() if v is True}
    trusted = trusted_marketplaces()
    foreign = sorted(p for p in plugins if p.rpartition("@")[2] not in trusted)
    for p in foreign:
        F.append(finding(f"posture:plugin:{p}", "posture", "medium", f"Plugin from an outside marketplace: {p}",
                         f"marketplace `{p.rpartition('@')[2]}` is not one of {', '.join(trusted)}",
                         "Check its hooks and MCP servers, or disable it in `enabledPlugins`.", group="posture"))
    if not foreign:
        passed.append("Plugins only from trusted marketplaces")
    servers = Counter(c["name"].split("__")[1] for _, c in calls if c["name"].startswith("mcp__") and c["name"].count("__") >= 2)
    mcp_files = sorted({k for d in settings.values() for k in (d.get("mcpServers") or {})})
    if plugins or servers or mcp_files:
        F.append(finding("posture:inventory", "posture", "low", "Extensions in use",
                         f"plugins: {', '.join(sorted(plugins)) or '-'} · MCP servers used: {top(servers, 8) or '-'}"
                         + (f" · configured in .mcp.json: {', '.join(mcp_files)}" if mcp_files else ""),
                         "Disable what you no longer use.", group="posture"))
    if not any(f["id"].startswith("posture:hook:") for f in F):
        passed.append("No hooks fetch remote code")
    return F


# ---------- acknowledging ----------

def load_acks(out_dir: Path = DIR) -> dict:
    return _load(out_dir / "acks.json") or {}


def with_acks(report: dict | None, acks: dict) -> dict | None:
    """The report with each finding flagged: reviewed (acked, no new session, severity not risen)
    or cameBack (acked, but it happened again or got worse). Nothing is dropped."""
    if not report:
        return report
    out = dict(report, findings=[])
    for f in report.get("findings", []):
        a = acks.get(f["fp"])
        ok = bool(a) and set(f.get("sessionIds", [])) <= set(a.get("sessions", [])) and SEV[f["severity"]] >= SEV.get(a.get("severity"), 0)
        out["findings"].append(dict(f, reviewed=ok, cameBack=bool(a) and not ok, ackedAt=a.get("at") if a else None))
    return out


def ack(fp: str, report: dict | None, undo: bool = False, out_dir: Path = DIR) -> bool:
    """Marks a finding of the report as reviewed (or not, with undo). False if it is not in the report."""
    f = next((f for f in (report or {}).get("findings", []) if f["fp"] == fp), None)
    acks = load_acks(out_dir)
    if undo:
        acks.pop(fp, None)
    elif not f:
        return False
    else:
        acks[fp] = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), "sessions": f.get("sessionIds", []),
                    "severity": f["severity"]}
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f"acks.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(acks, indent=1), encoding="utf-8")
    tmp.replace(out_dir / "acks.json")
    return True


# ---------- reports ----------

def save(report: dict, out_dir: Path = DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    data = json.dumps(report, indent=1, default=str)
    path = out_dir / f"{report['generatedAt'][:10]}.json"
    for p in (path, out_dir / "latest.json"):
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(p)
    for old in sorted(out_dir.glob("20*.json"))[:-KEEP]:
        old.unlink(missing_ok=True)
    return path


_latest: tuple[float, dict | None] = (0.0, None)


def latest(out_dir: Path = DIR) -> dict | None:
    """The newest report for the dashboard, re-read only when the file changed."""
    global _latest
    p = out_dir / "latest.json"
    try:
        mtime = p.stat().st_mtime
        if mtime != _latest[0]:
            _latest = (mtime, json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None
    return _latest[1]


def run(days: int, root: Path) -> dict:
    now = datetime.now().astimezone()
    t0 = time.monotonic()
    sessions = scan(root, now - timedelta(days=days))
    roots = {_repo_root(s["cwd"]) for s in sessions if s["cwd"]}
    report = analyze(sessions, read_all_settings(roots), days, now)
    report["stats"]["seconds"] = round(time.monotonic() - t0, 1)
    return report


def print_report(report: dict, path: Path | None) -> None:
    st = report["stats"]
    print(f"Claude Code security · last {report['days']} days · {st['sessions']} sessions, {st['toolCalls']} tool calls · "
          f"{st['high']} high, {st['medium']} medium, {st['low']} low · {st.get('seconds', '?')} s")
    for f in report["findings"]:
        refs = ", ".join(f"{r['project']} {r['id'][:8]}" for r in f["sessions"][:3])
        print(f"\n[{f['severity']:<6}] {f['title']}  ({f['group']})\n         {f['evidence']}\n      →  {f['fix']}"
              + (f"\n         sessions: {refs}" if refs else ""))
    print(f"\npassed: {'; '.join(report['passed']) or '-'}")
    if path:
        print(f"\nsaved {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=DAYS, help=f"look-back window (default {DAYS})")
    ap.add_argument("--projects-dir", type=Path, default=PROJECTS_DIR)
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--no-save", action="store_true", help="do not write the report files")
    args = ap.parse_args()
    report = run(args.days, args.projects_dir)
    path = None if args.no_save else save(report)
    if args.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        print_report(report, path)


if __name__ == "__main__":
    sys.exit(main())
