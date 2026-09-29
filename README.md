# paper-motion-kit

用 **Python（Pillow + numpy）+ ffmpeg** 產生水彩／紙張手作風教學影片動態圖形，取代 After Effects 字卡模板與轉場預置。同時是一個 Claude Code skill（見 `SKILL.md`）。

- 字卡：紙張質感、膠帶／圖釘、粉紅手繪圓圈高亮、彈入與淡出（標題／下三分之一／便利貼）
- 轉場：膠帶紙條、圖釘紙張、手繪彩帶（`tape` / `pin` / `line`）
- 雙語字幕：中英 SRT → ASS，可燒錄
- 批次：JSON 一次產出整批

示範影片：[assets/demo.mp4](assets/demo.mp4)

## 需求
Python 3.10+、`pip install pillow numpy`、ffmpeg/ffprobe（PATH 中）。預設字型為 Windows 微軟正黑體，其他系統以 `--font` 指定。

## 快速開始
```bash
python scripts/pmk.py card "今天學會 水彩暈染" --sub "Today: watercolor wash" --highlight "水彩暈染" -o title.mov
python scripts/pmk.py card "第一步" --layout lower --still 2 -o preview.png --opaque
python scripts/pmk.py join A.mp4 B.mp4 --style tape -o joined.mp4
python scripts/pmk.py overlay joined.mp4 title.mov --at 0.4 -o out.mp4
python scripts/pmk.py subs bilingual.srt --box --video out.mp4 -o final.mp4
python scripts/pmk.py batch examples/batch.json
```
完整選項見 `python scripts/pmk.py <cmd> -h` 與 `SKILL.md`。

## 作為 Claude Code skill 安裝
將本目錄複製為 `~/.claude/skills/paper-motion-kit/`。

## 限制
「水彩」感僅來自配色與紙紋，並非真實水彩暈染；手繪底圖需另以 AI 或 Blender 產生。

## License
MIT
