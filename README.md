# 3D Model Archive

使用 Vite、React、Tailwind CSS 與 Three.js 製作的靜態 3D 模型展示網站，可部署至 GitHub Pages 或其他 static hosting。

使用者功能請參考 `docs/01.spec.md`。

PC VR 展示桌、桌面預覽與 VIVE XR Elite / Pimax Crystal Super 的測試方式請參考 [VR 使用說明](docs/02.vr-preview.md)。

預設的 model-viewer 風格打光、色調映射與接觸陰影請參考 [攝影棚外觀](docs/03.studio-look.md)。

## 專案結構

```text
3d-gallery/
├─ docs/                   # 功能規格與專案文件
├─ enviroments/           # 環境全景原圖
├─ models/                # GLB 模型與同名縮圖，不納入 Git
├─ public/                # Service Worker 等公開檔案
├─ scripts/               # 模型清單與圖片最佳化腳本
├─ src/                   # React 應用程式
├─ .generated-assets/     # 建置時產生的最佳化資產
└─ dist/                  # Production build 輸出
```

`enviroments` 沿用目前專案既有的資料夾名稱與公開路徑拼字。

## 安裝與啟動

需求：Node.js 18 以上版本。

```bash
npm install
npm run dev
```

啟動前會自動：

- 掃描 `models/` 產生模型清單。
- 將模型縮圖轉換為 100×100 WebP。
- 將環境圖片轉換為最大寬度 2048px 的 WebP。
- 將暫存結果放入 `.generated-assets/`。

## 新增模型

將 GLB 與同名圖片放在 `models/` 的子資料夾：

```text
models/
└─ characters/
   ├─ robot.glb
   └─ robot.png
```

支援的縮圖來源格式：PNG、JPG、JPEG、WebP。

模型資料夾會成為網頁中的 folder 選項。新增或調整模型後需要重新啟動開發伺服器或重新 build。

## 新增環境圖片

將全景圖片放入 `enviroments/`。圖片會在開發與建置前自動轉換為 WebP。

環境選單目前由應用程式中的環境名稱表控制；新增圖片後也要加入對應名稱與檔名。

## Production Build

```bash
npm run build
```

完成後將 `dist/` 內容部署到 static hosting。

Vite 使用相對資源路徑，因此支援：

- 網域根目錄。
- GitHub Pages repository 子路徑。
- 其他掛載在子目錄的靜態網站。

本機檢查 production build：

```bash
npm run preview
```

## 部署注意事項

- Three.js、GLTFLoader 與 OrbitControls 從 jsDelivr CDN 載入，首次開啟網站需要能連線至 CDN。
- GLB、模型縮圖與環境圖片由網站本身提供，不依賴外部圖片 CORS。
- Production 環境會註冊 Service Worker，並以 cache-first 策略快取 GLB。
- 替換同一路徑的模型後，如需強制用戶更新快取，必須調整 Service Worker cache version。

## Git 忽略項目

以下內容不納入版本控制：

- `models/`
- `generated/`
- `.generated-assets/`
- `dist/`
- `node_modules/`
