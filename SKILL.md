---
name: paper-motion-kit
description: 以 Python（Pillow/numpy）＋ffmpeg 產生「水彩／紙張手作風」教學影片動態圖形：粉紅圓圈高亮字卡（標題／下三分之一／便利貼）、紙條圖釘／膠帶／手繪線條轉場、雙語字幕（ASS），可批次套用於所有影片，取代 After Effects 字卡模板與 Blender 素材的常見用法。使用者要做影片字卡、標題卡、轉場、雙語字幕、紙張質感動畫、教學影片包裝時使用。
---

# paper-motion-kit

單一 CLI：`python ~/.claude/skills/paper-motion-kit/scripts/pmk.py <cmd>`（需 Pillow、numpy、ffmpeg/ffprobe；預設字型取 Windows 微軟正黑體，可 `--font` 指定 ttf/ttc）。

## 指令

| cmd | 用途 |
|---|---|
| `card "文字" [--sub 英文] [--highlight 詞] [--layout title\|lower\|note] [--pin]` | 紙張字卡：淡入＋縮放彈入、文字上浮、粉紅手繪圓圈逐筆畫出、淡出。`\n` 換行 |
| `transition --style tape\|pin\|line` | 全螢幕轉場 alpha 片段：膠帶紙條橫掃／圖釘紙張彈入上滑／手繪彩帶分層滑過。中點完全遮蓋，可藏剪接點 |
| `join A.mp4 B.mp4 --style tape` | A、B 串接並把轉場疊在接點（自動縮放/補邊、音訊串接）。輸出長度＝A＋B |
| `overlay base.mp4 card.mov --at 3.2` | 將 alpha 字卡疊到指定時間 |
| `subs in.srt [--srt2 en.srt] [--box] [--video v.mp4 -o out.mp4]` | 雙語 SRT→ASS（中文大字＋英文小字，淡入淡出）；單檔每 cue 含中英兩行即可自動分辨；給 `--video` 直接燒錄 |
| `batch spec.json` | JSON 陣列，每項 `{"cmd":"card","args":["文字"],"out":"a.mov",...}`，一次產出整批 |

共通選項：`--theme watercolor|kraft|mono`、`--width/--height/--fps`、`--seed`（紙張／撕邊隨機）。
輸出：`--fmt mov`（ProRes4444 alpha，預設，剪輯軟體可直接疊）、`webm`（VP9 alpha）、`mp4`（不透明，紙色底）、`png`（序列）；`--opaque` 壓平至紙底；`--still T` 只輸出 T 秒單張 PNG 供預覽。

## 工作流程
1. 先用 `--still` 對版面/字型/顏色快速預覽（約 1 秒），確認再輸出影片。
2. 為整個系列統一 `--theme --seed --fps --width --height`，即等同 AE 的可重複使用模板；以 `batch` 套用所有解說段落。
3. 主軸剪輯（Premiere／ffmpeg）→ `join` 接轉場 → `overlay` 疊字卡 → `subs --video` 燒雙語字幕。順序：字幕最後燒，避免被轉場遮住。
4. 音樂／旁白對時：轉場長度預設 1.1s，遮蓋高點在 0.5–0.6s；`overlay --at` 以字卡起點計。

## 注意
- `join` 以 A 結尾往前 ½ 轉場長度為遮蓋中心，總長不縮短；若要「吃掉」重疊，先自行裁 A 尾/B 頭。
- 字卡 `--highlight` 需為 `text` 的子字串；只圈第一個出現處。
- 大量高解析輸出以 `--fps 30` 起；4K 時 Pillow 逐幀較慢，先 1080p 定稿。
- 需要手繪水彩底圖／插畫時，素材另以 AI 生成或 Blender 渲染，再作為 base 影片餵給本工具。
