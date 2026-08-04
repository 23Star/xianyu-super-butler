# 前端构建说明

该目录包含 React、TypeScript 和 Vite 前端源码。构建产物会写入项目根目录的 `static/`，由 FastAPI 统一提供。

```powershell
cd frontend
npm install
npm run build
cd ..
python Start.py
```

浏览器统一访问 `http://localhost:8080/`。

`npm run dev` 和 `npm run preview` 已禁用，避免启动与完整应用重复且缺少后端 API 的独立前端实例。
