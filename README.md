# Fed calendar feeds

Subscribable calendar links for Federal Reserve meetings that update themselves when the schedule changes.

- **`fomc.ics`**: FOMC meetings, read from the [FOMC meeting calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm). Includes past years shown on that page, the following year, notation votes and unscheduled meetings.
- **`board.ics`**: Board of Governors meetings, read from the [Board meetings RSS feed](https://www.federalreserve.gov/feeds/boardmeetings.xml). The feed only keeps recent items, so this calendar builds up history from the day you start it.

A GitHub Action runs once a day, rebuilds both files and commits them only if something changed. If an FOMC meeting is added, removed or moved, it also opens a GitHub issue, and GitHub emails you about it.

Everything here is free: a public GitHub repository, GitHub Actions and GitHub Pages.

## Setup (about 10 minutes)

1. **Create the repository.** Sign in to GitHub, click **New repository**, name it `fed-calendar`, make it **Public**, and create it with no files.
2. **Upload these files.** On the new repository's page, click **uploading an existing file**, drag in the contents of this folder (`scripts`, `.github`, `README.md`, `.gitignore`), and click **Commit changes**.
   - The `.github` folder is hidden on macOS. Press Cmd+Shift+. in Finder to show it before dragging.
   - If the upload skips it anyway, click **Add file → Create new file**, type `.github/workflows/update-calendar.yml` as the name, paste in that file's contents, and commit.
3. **Turn on GitHub Pages.** Go to **Settings → Pages**. Under *Build and deployment*, choose **Deploy from a branch**, branch **main**, folder **/docs**, and click **Save**.
4. **Run it once.** Go to the **Actions** tab, enable workflows if asked, click **Update Fed calendars → Run workflow**. After a minute you should see a green check and a new `docs/` folder in the repository.
   - If Pages complained in step 3 that `/docs` doesn't exist, go back and select it now.
5. **Get your links.** After a couple of minutes, Pages serves the files at:
   - `https://YOUR-USERNAME.github.io/fed-calendar/fomc.ics`
   - `https://YOUR-USERNAME.github.io/fed-calendar/board.ics`
   - `https://YOUR-USERNAME.github.io/fed-calendar/status.json` shows when it last checked.

## Subscribe in your calendar app

Subscribe by URL rather than importing the file. Importing makes a one-time copy that never updates.

- **Google Calendar (web):** Other calendars **+** → **From URL** → paste the link → **Add calendar**.
- **Apple Calendar:** File → **New Calendar Subscription** → paste the link → set **Auto-refresh** to *Every hour* or *Every day*.
- **Outlook (web):** Add calendar → **Subscribe from web** → paste the link → **Import**.

Google refreshes subscribed calendars on its own schedule, often every 12 to 24 hours, and it can't be forced. Apple and Outlook follow the interval you pick.

## How it behaves

- **Moved meetings update in place.** Each scheduled FOMC meeting has a fixed ID based on its year and starting month, so a date change within the month moves the event instead of adding a duplicate.
- **FOMC events are all-day**, spanning both meeting days. The description notes the 2:00 p.m. ET statement and 2:30 p.m. ET press conference, and meetings with projections are labeled.
- **Board events use the published start time.** The Fed doesn't publish end times, so each is shown as one hour. If a meeting was held at a different time than first announced, the description says so.
- **It fails loudly.** If the Fed redesigns its page and the script can't find this year's eight meetings, the run fails without publishing, and GitHub emails you that the workflow failed. The last good calendar stays online.

## Upkeep

- **GitHub pauses scheduled workflows after 60 days without repository activity.** The daily `status.json` update counts as activity, so this shouldn't happen. If it does, GitHub emails you and you can re-enable it from the Actions tab.
- **Notifications:** Change alerts arrive as GitHub issues. Make sure **Settings → Notifications** on GitHub has email turned on for issues in repositories you own.
- **Run it on demand:** Actions tab → **Update Fed calendars** → **Run workflow**.

## Testing locally

The script uses only the Python standard library (3.9 or newer).

```
python scripts/build_calendar.py                     # fetch live pages
python scripts/build_calendar.py page.html feed.xml  # use saved copies instead
```
