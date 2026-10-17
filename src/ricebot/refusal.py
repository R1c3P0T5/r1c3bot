"""What to tell a member when Discord turns a request down."""

import discord


def text(error: discord.HTTPException) -> str:
    """Discord's own words for the refusal, trimmed to what reads as a sentence.

    Only the first line is prose; the rest of an HTTPException is its JSON body.
    """
    return f"Discord 回報 {str(error).splitlines()[0][:80]}"
