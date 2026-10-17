"""The words the CTF cog says, apart from the gateway that sends them."""

from datetime import datetime, timedelta

from ricebot import clock
from ricebot.ctf import ctftime
from ricebot.store.ctf import Contest

# Reacting with this emoji opens the discussion channel.
RSVP = "🚩"
# CTFtime's restriction values. Open is not printed, and Casual still lets
# anyone enter.
OPEN = "Open"
CASUAL = "Casual"
RESTRICTION_LABELS = {"Academic": "限學生", "High-school": "限高中生", "Invited": "邀請制"}

NO_CATEGORY = "還沒設定 CTF 討論頻道分類，請管理員用 `/config` 設定"
NO_ARCHIVE_CATEGORY = "還沒設定 CTF 封存分類，請管理員用 `/config` 設定"
NOTHING_OPEN = "現在沒有在追蹤的比賽。"
NOT_TRACKED = "找不到這場。在它的討論頻道裡執行，或用選單指定一場。"
ARCHIVED_ALREADY = "這場已經封存過了。"
BAD_NUMBER = "三個欄位都要是數字，而且在標示的範圍內。"
ANNOUNCE_POSTED = "已發布"
ANNOUNCE_MISSING = "未發布，原因在 log"
EVENT_CREATED = "已建立"
EVENT_MISSING = "未建立（已經開始，或 Discord 拒絕）"
# A reply takes 2000 characters, and a line with a link approaches a hundred.
LISTED = 15
# A guild event's description takes 1000 characters, markup and all.
EVENT_LIMIT = 1000


def duration_text(span: timedelta) -> str:
    days, hours = divmod(round(span.total_seconds() / 3600), 24)
    if days and hours:
        return f"{days} 天 {hours} 小時"
    return f"{days} 天" if days else f"{hours} 小時"


def facts(contest: Contest, emphasis: str = "") -> list[str]:
    """What the contest is, for the message and for the guild event alike."""
    where = f"實體（{contest.location}）" if contest.onsite else "線上"
    casual = "休閒" if contest.restrictions == CASUAL else ""
    kind = " ".join(part for part in (where, contest.format, casual) if part)
    # CTFtime counts the teams registered, so a contest announced early has 0.
    teams = f"{contest.participants} 隊" if contest.participants else ""
    span = duration_text(contest.finishes_at - contest.starts_at)
    lines = [" ".join(p for p in (kind, f"(weight {contest.weight:.2f})", teams, span) if p)]
    if contest.restrictions not in {OPEN, CASUAL, ""}:
        # Its own line, because being unable to enter outranks everything else.
        limit = RESTRICTION_LABELS.get(contest.restrictions, contest.restrictions)
        lines.append(f"{emphasis}{limit}（{contest.restrictions}）{emphasis}")
    if contest.organizers:
        lines.append(f"主辦：{contest.organizers}")
    return lines


def summary(contest: Contest) -> str:
    """The contest, as both the announcement and its own channel introduce it."""
    lines = [f"## {contest.title}", *facts(contest, "**")]
    # Angle brackets so two links do not become two embeds.
    lines.append(f"[官網](<{contest.url}>) ‧ [CTFtime](<{contest.page}>)")
    # The times go last: the client renders each as some 60 characters, which
    # above the facts would crowd them out. The short style drops the weekday.
    lines += [
        "",
        (
            f"{clock.stamp(contest.starts_at, 'f')} ～ {clock.stamp(contest.finishes_at, 'f')}"
            f"（{clock.stamp(contest.starts_at, 'R')}開始）"
        ),
    ]
    return "\n".join(lines)


def listed(contest: Contest, link: str | None) -> str:
    """One line of the list: when it starts, what it is, where it is discussed."""
    title = contest.title if link is None else f"[{contest.title}](<{link}>)"
    where = f" <#{contest.channel_id}>" if contest.channel_id is not None else ""
    return f"`{clock.taipei(contest.starts_at):%m/%d %H:%M}` {title}{where}"


def announce(contest: Contest) -> str:
    return f"{summary(contest)}\n\n想打的按個 {RSVP}，我開一個討論頻道給你們。"


def channel_opened(contest: Contest) -> str:
    """The channel's first message: a hello, the summary, and CTFtime's blurb."""
    hello = f"{contest.title} 用的頻道開了！後續的討論和 write-up 都可以丟這裡"
    parts = [hello, summary(contest)]
    if contest.description:
        parts.append(contest.description)
    return "\n\n".join(parts)


def event_description(contest: Contest) -> str:
    """The same facts as the announcement, then as much blurb as still fits."""
    head = "\n".join([*facts(contest), contest.url, contest.page])
    blurb = ctftime.shorten(contest.description, EVENT_LIMIT - len(head) - 2)
    return f"{head}\n\n{blurb}" if blurb else head


def wrap_up(closes_at: datetime) -> str:
    """Told to the channel when the contest ends: when the channel closes."""
    return (
        f"比賽結束！辛苦了🙌\n這個頻道會在 {clock.taipei(closes_at):%m/%d} 收起來，但內容都還會在"
    )
