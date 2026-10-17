"""The words the book club says, apart from the gateway that sends them."""

from collections.abc import Sequence
from datetime import date

from ricebot import clock
from ricebot.store.bookclub import Session

CLUB_NAME = "讀書會"
UNASSIGNED = "未指派"
# Reacting with this emoji signs up, and the reactions are the whole list.
RSVP = "🚩"
SCHEDULE_LABEL = "排下一場"

NO_SESSION = "現在沒有排定的場次，要不要用 `/bookclub new` 開一場？"
HOST_ONLY = "這個只有本場主持人或管理員動得了。"
NO_HOST = "這場還沒有主持人。"
SAME_TIME = "這場本來就是那個時間。"
SLOT_TAKEN = "那個時間已經有一場了，先取消那場或者改去別的時間。"
BAD_TIME = "日期要寫成 YYYY-MM-DD、時間寫成 HH:MM。"
NO_HISTORY = "還沒有結束的場次。"

# What /bookclub new reports for the event and for the announcement.
EVENT_CREATED = "已建立"
EVENT_KEPT = "沿用原本那個"
EVENT_NO_VOICE = "未建立（還沒設定讀書會語音頻道，請管理員用 `/config` 設定）"
EVENT_IN_PAST = "未建立（不能建立過去的活動，Discord 不接受）"
ANNOUNCE_POSTED = "已發布"
ANNOUNCE_KEPT = "沿用原本那則"
ANNOUNCE_NO_CHANNEL = "未發布（還沒設定讀書會公告頻道，請管理員用 `/config` 設定）"

_WEEKDAYS = "一二三四五六日"


def day_choice(day: date) -> str:
    """A date as the picker lists it."""
    return f"{day:%m/%d}（週{_WEEKDAYS[day.weekday()]}）"


def mention(user_id: int | None, fallback: str = UNASSIGNED) -> str:
    return f"<@{user_id}>" if user_id is not None else fallback


def announce(session: Session, role_id: int | None) -> str:
    """The announcement: the session's host, topic, time and sign-up prompt."""
    lines = [] if role_id is None else [f"<@&{role_id}>"]
    lines += [
        f"## 📚 {CLUB_NAME}{f' · {session.topic}' if session.topic else ''}",
        f"{clock.stamp(session.starts_at)} {clock.stamp(session.starts_at, 'R')}",
        f"主持人：{mention(session.host_user_id)}",
    ]
    if session.cancelled_at is not None:
        lines.append("\n**這場取消了**，時間不用留著。下一場排好我再回來喊人。")
    else:
        lines.append(f"\n想來的按個 {RSVP}，開始前會提醒你。")
    return "\n".join(lines)


def event_name(topic: str | None) -> str:
    # Discord caps an event name at 100 characters.
    return f"{CLUB_NAME}：{topic[:80]}" if topic else CLUB_NAME


def event_description(host_name: str | None, topic: str | None) -> str:
    """The event's body, as plain text: a mention would not render there."""
    lines = []
    if host_name is not None:
        lines.append(f"主持人：{host_name}")
    if topic:
        lines.append(f"主題：{topic}")
    return "\n".join(lines)


def roll_call(attendees: Sequence[int]) -> str:
    """Who has signed up, for a reminder to read out."""
    if not attendees:
        return f"目前還沒有人按 {RSVP}，臨時加入也沒問題。"
    return "報名的有 " + " ".join(mention(user_id) for user_id in attendees) + "，到時候見。"


def history_line(session: Session) -> str:
    """One past session: the date, the host, the topic."""
    note = "（已取消）" if session.cancelled_at else ""
    day = f"{clock.taipei(session.starts_at):%Y/%m/%d}"
    return f"`{day}` {mention(session.host_user_id)} {(session.topic or '—')[:40]}{note}"
