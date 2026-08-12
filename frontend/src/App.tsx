import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Dashboard } from "./pages/Dashboard";
import { Sessions } from "./pages/Sessions";
import { SessionDetail } from "./pages/SessionDetail";

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-[#05070a]">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/sessions" element={<Sessions />} />
          <Route path="/sessions/:sessionId" element={<SessionDetail />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}

export default App;
