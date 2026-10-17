# ricebot

r1c3p0t5 社群經營用的 Discord bot。

## Feature

- `/config` — 設定 bot 使用的頻道與分類：讀書會公告、讀書會語音、CTF 公告、CTF 討論、CTF 封存
- `/bookclub new <day> <at> <host> <topic>` — 排一場，在讀書會頻道發報名表並建立 Discord 活動
- `/bookclub host <user> [when]` — 換這場的主持人，不影響誰下次輪到
- `/bookclub skip [when]` — 這場先過，下一場仍然優先
- `/bookclub topic <text> [when]` — 設定這場的主題
- `/bookclub cancel [when]` — 取消這場，連活動一起撤掉
- `/bookclub next` — 下一場的時間、主持人與主題
- `/bookclub history [count]` — 過去的場次與主題
- `/bookclub role <role>` — 設定讀書會身分組：輪替名單與提醒的對象
- `/ctf upcoming` — 接下來追蹤中的比賽
- `/ctf announce <ctftime_id>` — 手動公告一場，不經過篩選條件
- `/ctf archive [contest]` — 手動封存一場的討論頻道，在它的頻道裡執行可以不給參數
- `/ctf config` — 調整權重門檻、往後看幾天、結束幾天後封存

`[when]` 不給就是下一場。
`/config`、`/ctf announce`、`/ctf archive`、`/ctf config` 與 `new`、`cancel`、`role` 需要 Manage Server，`host`、`skip`、`topic` 限本場主持人或管理員，其餘不限。
指令的回覆只有自己看得見，公開訊息一律發在對應頻道。

CTF 揪團的自動部分：

- 每 6 小時從 CTFtime 抓未來 21 天（預設）的比賽，留下有權重、非 onsite、不是 `Prequalified` 的場次，發公告並建立活動。
- 門檻與天數都能用 `/ctf config` 調；`/ctf announce` 不受篩選限制，onsite 或未評分的比賽也收得進來。
- 按 🚩 就進該場的私密討論頻道；頻道等第一個 🚩 才開，取消 🚩 只移除權限，頻道留著。
- 比賽一結束，討論頻道裡會說哪一天收起來；真的要搬的時候再說一聲。
- 比賽結束兩天（預設）後，頻道搬到封存分類並設為唯讀，原本的成員仍讀得到。
- 開頻道或封存失敗時（分類沒設定、分類滿了、缺權限），會在 CTF 公告頻道說出原因。

讀書會在指令以外的部分：

- 報名表是這場的規範現況（主持人、主題、🚩 名單），改動一律編輯它，後續通知只給連結指回來。
- 報名以報名表上的 🚩 為準，活動頁面的「感興趣」不算。
- 提醒在開始前 1 天與 1 小時發出，結束後的那則說出下一棒輪到誰，並帶一顆「排下一場」按鈕，誰都能按。

## Environment

- Python 3.13（`uv` 會依 `.python-version` 自動準備）
- [uv](https://docs.astral.sh/uv/)
- 一個 Discord application 與 bot token，並在 Developer Portal 開啟 **Server Members Intent**
- 邀請時的 `permissions` 值為 `17601044499536`

Server Members Intent 屬於 privileged intent，但 100 個伺服器以下的 bot 只要在 Developer Portal 打開開關，不需要審核。
主持人輪替要讀取身分組的成員，而 Discord 沒有其他 API 能取得這份清單。
Message Content Intent 不要開，沒有任何功能讀訊息內容。

權限值裡容易漏掉 `Create Events`（`1 << 44`）。
Discord 把建立活動與管理活動拆成兩個權限，`Manage Events`（`1 << 33`）只能改別人建立的活動。
缺它的症狀是場次排得起來但活動建不出來，log 留下 `403 Missing Permissions`。

公告與提醒另外需要 `View Channel`、`Send Messages`、`Add Reactions` 與 `Read Message History`。
最後一項容易漏：提醒要點名報名者，而讀出 🚩 的名單得先抓回公告訊息。

讀書會身分組要設為「可提及」（role settings 的 *Allow anyone to @mention this role*）。
否則公告裡的身分組提及不會通知任何人，而讓 bot 無視這個開關的唯一辦法是給它 `Mention Everyone`，權限範圍遠大於需要。

鎖定 3.13 而非 3.14 的原因：`discord.py` 的 `speed` extra 對 `zstandard` 標了 `python_version <= "3.13"`。
在 3.14 上它會被略過，等於靜默失去 gateway 的 zstd 壓縮。

## 安裝

```sh
git clone <repo> && cd ricebot
uv sync
uv run pre-commit install       # 每個 clone 做一次
cp .env.example .env            # 填入 token 與 GUILD_ID
```

## 執行

```sh
uv run --env-file .env ricebot
```

`uv run` 不會自己讀 `.env`，所以本機執行要指明。
部署時則由 systemd 的 `EnvironmentFile` 提供，不經過 uv。
缺少或填錯的變數會在啟動時一次全部列出。

## 設定

`.env` 只放 token、`GUILD_ID` 與資料庫路徑，也就是改了必須重啟才會生效的值。

其餘設定在 Discord 裡用 `/config` 調整，寫進資料庫、即時生效、重啟保留。
指令限定 `Manage Server` 權限，面板上每個項目是一個頻道選單，不需要複製 ID。

## 開發

```sh
uv run pytest                        # 全部測試
uv run pytest tests/test_schedule.py # 單一檔案
uv run pre-commit run --all-files    # 所有 hook
```

`pre-commit` 只檢查 tracked 檔案，所以新增的檔案要先 `git add` 再跑。

Ruff 設定在 `ruff.toml`，不在 `pyproject.toml`，且刻意不列為 dev 依賴。
它的版本已由 `.pre-commit-config.yaml` 的 `rev` 釘住，放兩份會有版本漂移的風險。
Ruff 一律透過 pre-commit 執行。

## 部署

以 systemd **user** service 執行，資料庫是本機 SQLite 檔案。
bot 不綁 port、不需特權資源，所以不需要 system unit，也因此整個部署流程**不需要 sudo**。

首次安裝：

```sh
git clone <repo> ~/ricebot && cd ~/ricebot
uv sync
cp .env.example .env                      # 填入 token 與 GUILD_ID
mkdir -p ~/.config/systemd/user
cp deploy/ricebot.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ricebot
loginctl enable-linger "$USER"
```

最後一行不能省：沒有 linger，systemd 的 user manager 會在你最後一個登入 session 結束時關閉，bot 會在你登出時一起被關掉。

`.env` 由 systemd 自己解析（`EnvironmentFile`），只接受單純的 `KEY=value`。
不要寫 `export`，也不要用 `$OTHER` 這類 shell 展開。

升級：

```sh
cd ~/ricebot && git pull && uv sync && systemctl --user restart ricebot
```

查看狀態與日誌：

```sh
systemctl --user status ricebot
journalctl --user -u ricebot -f
```

版本號由 git tag 透過 `uv-dynamic-versioning` 推導。
踩在 tag 上時是乾淨的 `1.2.0`，tag 之後有 commit 則會帶上 commit hash（`1.2.0.post3+ab12c52`）。
因此版本字串本身就足以辨識跑著的是哪一份 code。

SemVer 的語意以「部署動作」為 consumer。
`patch` 與 `minor` 只需上面那三步，`major` 代表升級需要額外手動處理：無法自動執行的 migration、新的 `.env` 欄位、或需要在 Developer Portal 另外開啟的 intent 與權限。
