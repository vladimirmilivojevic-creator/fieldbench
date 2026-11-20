// Where the bench API lives. Local development uses the uvicorn dev server.
window.FIELDBENCH_API = ["localhost", "127.0.0.1"].includes(location.hostname)
  ? "http://127.0.0.1:8000"
  : "https://fieldbench-api.onrender.com";
