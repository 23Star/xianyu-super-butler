# 前端构建说明

该目录只负责生成完整应用使用的静态资源，不提供独立开发服务器。

```powershell
cd frontend
npm install
npm run build
cd ..
python Start.py
```

浏览器统一访问 `http://localhost:8080/`。

`npm run dev` 和 `npm run preview` 已禁用，避免启动与完整应用重复的前端实例。
