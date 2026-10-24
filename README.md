# sprite-gen

用一張角色圖，產生可供遊戲使用的 2D Sprite Atlas。

`sprite-gen` 的原則是：AI 只負責畫每個動畫狀態的姿勢；去背、切 frame、對齊、打包、manifest 和 QA 全部由程式 deterministic 地完成。

```text
角色 base image
  → request / layout guides / prompts
  → 每個 state 一張 AI horizontal row
  → chroma 去背 + connected components 切 frame
  → optional 人手整理
  → atlas + manifest + QA
```

最終遊戲資產是：

```text
sprite-sheet-alpha.png + manifest.json
```

遊戲必須使用 `manifest.json.frame_layout` 的矩形位置，不要自行猜 grid、掃 alpha 或直接使用 raw row。

## 1. 安裝環境

需要 Python 3.10+、Codex image generation（或 Grok）及 repo 專用 virtualenv。

```bash
export SPRITE_GEN_ROOT=/absolute/path/to/sprite-gen
python3 -m venv "$SPRITE_GEN_ROOT/.venv"
"$SPRITE_GEN_ROOT/.venv/bin/pip" install -e "$SPRITE_GEN_ROOT"
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" --help
```

不要依賴 global `python3` 執行 pipeline；它可能沒有正確版本的 Pillow 或 NumPy。

### 安裝成 Codex skill

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo aldegad/sprite-gen --path . --name sprite-gen
```

### 確認 Codex image generation

```bash
codex login status
codex --version
```

如果使用 Codex，帳戶必須提供內置 `image_gen` capability。`$imagegen` 只是一個呼叫名稱，不能自行開通 capability。

## 2. 準備 base image（Base Lock）

Base image 是 identity 和 style 的起點。開始 pipeline 前，確認：

- 全身完整，沒有裁切。
- 臉、髮型、衣服、配色、比例、道具都正確。
- silhouette 在小尺寸仍清楚。
- 背景是單色、容易去背。
- 如果要 pixel art，base 本身已是真正 pixel art；不要靠最後 resize 製造 pixel art。

通用輸入模板：

```text
base.png
  - 一個完整角色
  - 一個清楚 idle pose
  - 單色背景
  - 檔案路徑：/absolute/path/to/base.png
```

弱 base 會令所有動畫 state 一起 identity drift；未通過 Base Lock 不要繼續。

## 3. 建立 run（Prepare）

`prepare` 會建立 request、guides、prompts 及輸出目錄。

```bash
RUN="$SPRITE_GEN_ROOT/runs/demo-hero"

"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" prepare \
  --out-dir "$RUN" \
  --character-id demo-hero \
  --base-image /absolute/path/to/base.png \
  --description "small red-haired adventurer with a blue tunic" \
  --cell-width 64 \
  --cell-height 96
```

會產生：

```text
$RUN/
  sprite-request.json
  base-source.png
  references/layout-guides/<state>.png
  prompts/<state>.txt
  raw/
  frames/
```

`sprite-request.json` 是數字規格的 single source of truth，包括 cell size、states、frame count、fps、loop、chroma key 和 fit options。

### 自訂 states 模板

建議 simple MVP 使用 4 frames：

```json
{
  "states": {
    "idle":   { "frames": 4, "fps": 4, "loop": true,  "action": "subtle breathing and one blink" },
    "jump":   { "frames": 4, "fps": 8, "loop": false, "action": "crouch, takeoff, airborne, landing" },
    "attack": { "frames": 4, "fps": 8, "loop": false, "action": "windup, strike, recovery, rest" },
    "wave":   { "frames": 4, "fps": 6, "loop": false, "action": "friendly hand wave while feet stay planted" }
  }
}
```

實際 request 應透過 `prepare --request-json` 或 repo 支援的 request workflow 寫入；修改 request 後，要重新產生 guides、prompts、frames 和 atlas。

## 4. 逐個 state 生成 AI row

每個 state 只生成一張 horizontal row。不要叫 AI 一次過生成 master atlas。

```bash
STATE=idle

"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" gen \
  --provider codex \
  --prompt-file "$RUN/prompts/$STATE.txt" \
  --out "$RUN/raw/$STATE.png" \
  --ref "$RUN/base-source.png" \
  --ref "$RUN/references/layout-guides/$STATE.png"
```

其他 state 只需改 `STATE`：

```text
idle   → raw/idle.png
jump   → raw/jump.png
attack → raw/attack.png
wave   → raw/wave.png
```

`raw/<state>.png` 必須保留 chroma background，因為下一步 extractor 會負責去背。

Codex 是 default provider；需要指定 Grok 時：

```bash
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" gen \
  --provider grok --prompt-file "$RUN/prompts/idle.txt" \
  --out "$RUN/raw/idle.png"
```

Batch 可最多約 4 個不同 state 並行，但每個 state 必須寫入不同 raw file。

## 5. Extract transparent frames

```bash
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" extract \
  --run-dir "$RUN"
```

Extractor 會依次執行：

```text
chroma background removal
  → alpha / despill cleanup
  → connected components 找姿勢
  → 驗證 frame 數量
  → fit 每個姿勢到共用 cell
  → 寫入 frames-manifest.json
```

成功後：

```text
$RUN/frames/<state>/frame-N.png
$RUN/frames/frames-manifest.json
```

如果要求 4 frames 但只找到 3 個，這一步應該失敗；不要把錯誤 row 當成功輸出。`--allow-slot-fallback` 只適合明確 debug，不是 production pass。

### Chroma key 注意事項

- 粉紅、紫色、紅色角色通常使用 green key。
- 綠色、青綠色角色通常使用 magenta key。
- 主要角色顏色被刪除時，應改 chroma key 並重新生成，不要事後硬修。

## 6. Pixel-unfake（可選）

需要 pixel-art output 時，在 prepare/request 開啟 `fit.pixel_unfake`。它會使用：

```text
pixel pitch detection
  → row-wide shared grid
  → integer grid snap
  → shared palette
  → deterministic NEAREST placement
```

單純 `PIL.resize()` 不等於 pixel-unfake。pixel-art base 也必須先通過真 pixel-grid 檢查。

## 7. 預覽及 QA

先產生動畫預覽：

```bash
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" preview \
  --run-dir "$RUN"
```

輸出會放在：

```text
$RUN/qa/<state>-contact.png
$RUN/qa/<state>.gif
```

再執行 machine checks：

```bash
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" inspect --run-dir "$RUN"
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" score \
  --inspect-report "$RUN/sprite-inspect.report.json" \
  --output "$RUN/sprite-score.report.json"
```

驗收至少包括：

- 每個 state 的 frame 數量正確。
- 沒有空 frame、殘留背景或過多 edge pixels。
- 角色 identity、比例、顏色在 frame 之間穩定。
- `idle` loop seam 順暢。
- `jump`、`attack`、`wave` 有清楚的開始、中段和結束。
- 沒有 broken anatomy、額外手腳或嚴重 jitter。

失敗時重新生成該 state；不要用本地重畫或單純 re-time 偽裝成成功。把人工 verdict 寫入：

```text
$RUN/qa-notes.md
```

## 8. 人手整理（可選但建議）

```bash
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" curation --run-dir "$RUN"
```

Webview 可以選擇/排除 frame、重新排序、從 candidate pool 揀 take，以及 move、scale、rotate、shear、flip 和 pixel edits。

修改會寫入：

```text
$RUN/curation.json
```

原本 `frames/` 不會被覆蓋。沒有 `curation.json` 時，composer 會明確使用所有 frame、原次序和 identity transform。

## 9. 生成 Sprite Atlas

如果有 curation，應在 curation 完成後 compose：

```bash
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" compose-atlas \
  --run-dir "$RUN"
```

輸出：

```text
$RUN/sprite-sheet-alpha.png
$RUN/manifest.json
$RUN/sprite-sheet-alpha.report.json
```

`manifest.json` 會包含 `game_input`、每個 state 的 animation metadata、`frame_layout.rows.<state>` absolute rectangles，以及 `degraded_static_fallback: false`。

## 10. 遊戲端接入模板

```text
讀取 sprite-sheet-alpha.png
讀取 manifest.json
選擇 state
按 frame index 取 manifest.frame_layout.rows[state][index]
只渲染該 rectangle
按 durations_ms 或 fps 播放
```

不要整張 atlas 當單一 sprite、猜 grid、掃 alpha，或使用 raw row。若有 curation，也不要直接把 `frames/` 複製入遊戲。

## 11. 可選功能

### Breathe

由 idle frame deterministic 地產生呼吸效果，不需要重新叫 AI：

```json
"breathe": { "depth": 0.05, "breaths": 3 }
```

通常放入 `curation.json` 後再重新 compose/GIF。

### Recolor

```bash
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" recolor-palette \
  --base "$RUN/sprite-sheet-alpha.png" --out "$RUN/palette.draft.json"
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" recolor \
  --run-dir "$RUN" --spec "$RUN/recolor.spec.json"
```

輸出會放在 `$RUN/variants/`；alpha 和 geometry 不變。

### Direction / 45-degree anchors

```bash
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" prepare \
  --out-dir "$RUN" --character-id hero \
  --base-image /absolute/path/to/base.png \
  --directions down,side,up --mirror left=side
```

方向角色應先建立每個方向的單 pose idle anchor，再生成 action row。action row 使用相應 anchor 作 identity reference；basis row 只作 motion rhythm reference。

### Layer composite

只有 request 宣告 `rig` / `layers` 時才使用：

```bash
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" compose-layers --run-dir "$RUN"
```

輸出在 `$RUN/layers/`；composite 不是 `frames/` 中的新 state。

### Aseprite / GIF / individual PNG

```bash
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" export-aseprite --run-dir "$RUN"
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" compose-gif --run-dir "$RUN"
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" export-pngs --run-dir "$RUN" --selected-only
```

individual still PNG 應從 `$RUN/curated/` 交付，而不是直接複製 `frames/`。

## 12. 由現有 atlas 或 PNG 候選重新開始

只有 atlas：

```bash
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" unpack-atlas \
  --atlas /absolute/path/to/sheet.png \
  --out-dir "$SPRITE_GEN_ROOT/runs/imported" --force
```

一堆 PNG 候選：

```bash
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" unpack-atlas \
  --pngs-dir /absolute/path/to/candidates \
  --out-dir "$SPRITE_GEN_ROOT/runs/candidates" --force
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" curation \
  --run-dir "$SPRITE_GEN_ROOT/runs/candidates"
```

這是 import/curation workflow，不是新的 AI row generation。

## 13. Run 完成檢查表

```text
[ ] Base image 已 lock
[ ] sprite-request.json 正確
[ ] 每個 state 都有 raw row
[ ] frames-manifest.json.ok == true
[ ] 每個 state frame count 正確
[ ] GIF/contact sheet motion 通過
[ ] sprite-inspect.report.json 無 blocking error
[ ] sprite-score.report.json 通過
[ ] 如有修改，已完成 curation
[ ] sprite-sheet-alpha.report.json.ok == true
[ ] manifest.json.frame_layout 存在
[ ] 遊戲使用 atlas + manifest，而不是 frames/
```

## 14. 常見問題

### Codex 沒有 image generation

```bash
codex login status
```

確認登入的是提供 built-in `image_gen` 的 Codex account/state root。若要改用 Grok：

```bash
"$SPRITE_GEN_ROOT/.venv/bin/sprite-gen" gen --provider grok ...
```

明確指定 `--provider codex` 時，如果 Codex 不可用會直接失敗；不會靜默產生 static fallback。

### Installer 顯示 `Invalid skill name`

重新執行並加入 `--name sprite-gen`：

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo aldegad/sprite-gen --path . --name sprite-gen
```

### 生成圖有 guide box、文字、重疊姿勢或裁切

該 raw row 不合格。重新生成該 state，不要把它直接送入 atlas。

### 只有一張靜態圖但想交付動畫

靜態圖可以作為 base；若沒有真正生成及 QA 過的動畫 row，不能宣稱 full sprite animation pass。可另外使用 `breathe` 作 deterministic idle motion，但要在 QA 中標明。

## 延伸文件

- [SKILL.md](SKILL.md)：行為 contract 及完整 agent workflow。
- [docs/run-contract.md](docs/run-contract.md)：run folder、stage input/output、manifest contract。
- [docs/architecture.md](docs/architecture.md)：程式內部架構及 ownership。
- [docs/gen.md](docs/gen.md)：Codex/Grok provider、驗證和 fallback policy。
- [docs/curation.md](docs/curation.md)：webview、curation sidecar、import workflow。
- [docs/qa-motion.md](docs/qa-motion.md)：motion continuity 判定。
- [docs/chroma-alpha.md](docs/chroma-alpha.md)：chroma key 選擇和 alpha cleanup。
- [docs/pixel-unfake.md](docs/pixel-unfake.md)：pixel-unfake 參數及規則。

## License

Apache-2.0
