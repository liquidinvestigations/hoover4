"""Manual procedure manual-dates."""

from __future__ import annotations

PROCEDURE_NAME = 'manual-dates'


async def run(r):
    async def bounds(start="2001-01-01", end="2010-12-31"):
        await r.search()
        await r.modal("Date")
        await r.click("Between…", "#x-filter-modal")
        await r.type('#x-filter-modal input[type="date"]:first-of-type', start)
        await r.action("eval", "const es=[...document.querySelectorAll('#x-filter-modal input[type=date]')];if(es.length!==2)throw Error('date inputs unavailable');es[1].id='qa-date-end';return true;")
        await r.type("#qa-date-end", end)
    async def baseline():
        from datetime import datetime, timezone
        start, end = "2001-01-01", "2010-12-31"
        await bounds(start, end)
        await r.apply()
        minimum = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp())
        maximum = int(datetime.fromisoformat(end).replace(tzinfo=timezone.utc).timestamp()) + 86399
        return await r.expected_results(x["hash"] for x in r.metadata()["dates"] if minimum <= int(x["date"]) <= maximum)
    await r.phase("baseline", "Each date-filter result has a confirmed source date within the inclusive bounds.", baseline)
    await r.phase("boundary-input", "Keyboard input applies both date boundaries.", baseline)
    async def reversed_dates():
        await bounds("2010-12-31", "2001-01-01")
        await r.text("The start date is after the end date.", "#x-filter-modal")
        await r.type("#qa-date-end", "2011-01-01")
        await r.apply()
        return await r.check("return !document.querySelector('.x-error-display');")
    await r.phase("reversed-dates", "An inverted interval displays an error and corrected bounds recover.", reversed_dates)
