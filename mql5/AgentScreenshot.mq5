//+------------------------------------------------------------------+
//| AgentScreenshot.mq5                                              |
//| File-bridge EA for mt5-trading-mcp get_chart_screenshot.        |
//| Polls MQL5/Files/agent_screenshot/*.req, opens the requested    |
//| chart, calls ChartScreenShot(), writes <id>.png + <id>.done.    |
//| Pairs with src/mt5_mcp/adapter/screenshot.py.                   |
//+------------------------------------------------------------------+
#property strict
#property description "mt5-trading-mcp chart screenshot bridge"

input int TimerMs  = 200;   // poll interval (ms)
input int SettleMs = 400;   // wait after ChartOpen before capture (ms)

const string SubDir = "agent_screenshot";

int OnInit()
  {
   EventSetMillisecondTimer(TimerMs);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

ENUM_TIMEFRAMES TfFromName(const string name)
  {
   if(name=="M1")  return(PERIOD_M1);
   if(name=="M5")  return(PERIOD_M5);
   if(name=="M15") return(PERIOD_M15);
   if(name=="M30") return(PERIOD_M30);
   if(name=="H1")  return(PERIOD_H1);
   if(name=="H4")  return(PERIOD_H4);
   if(name=="D1")  return(PERIOD_D1);
   if(name=="W1")  return(PERIOD_W1);
   if(name=="MN1") return(PERIOD_MN1);
   return((ENUM_TIMEFRAMES)-1);
  }

void WriteDone(const string id, const string status)
  {
   string path = SubDir + "\\" + id + ".done";
   int h = FileOpen(path, FILE_WRITE|FILE_TXT|FILE_UNICODE);
   if(h != INVALID_HANDLE)
     {
      FileWriteString(h, status);
      FileClose(h);
     }
  }

void ProcessRequest(const string reqName)
  {
   // reqName is just "<id>.req" (from FileFindFirst); prefix the subdir.
   string reqPath = SubDir + "\\" + reqName;
   int h = FileOpen(reqPath, FILE_READ|FILE_TXT|FILE_UNICODE);
   if(h == INVALID_HANDLE)
      return;
   string line = FileReadString(h);
   FileClose(h);
   FileDelete(reqPath);

   string parts[];
   int n = StringSplit(line, '|', parts);
   if(n < 5)
     {
      if(n >= 1)
         WriteDone(parts[0], "err:malformed request");
      return;
     }

   string id       = parts[0];
   string symbol   = parts[1];
   string tfName   = parts[2];
   int    width    = (int)StringToInteger(parts[3]);
   int    height   = (int)StringToInteger(parts[4]);
   string tpl      = (n >= 6) ? parts[5] : "";

   ENUM_TIMEFRAMES tf = TfFromName(tfName);
   if(tf == (ENUM_TIMEFRAMES)-1)
     {
      WriteDone(id, "err:bad timeframe " + tfName);
      return;
     }

   long cid = ChartOpen(symbol, tf);
   if(cid == 0)
     {
      WriteDone(id, "err:ChartOpen failed for " + symbol);
      return;
     }

   if(StringLen(tpl) > 0)
      // Best-effort: a bad or missing template name falls back to the default
      // chart rather than failing the capture. Return value intentionally ignored.
      ChartApplyTemplate(cid, tpl);

   ChartRedraw(cid);
   Sleep(SettleMs);

   string pngPath = SubDir + "\\" + id + ".png";
   bool ok = ChartScreenShot(cid, pngPath, width, height, ALIGN_RIGHT);
   ChartClose(cid);

   WriteDone(id, ok ? "ok" : "err:ChartScreenShot returned false");
  }

void OnTimer()
  {
   string names[];
   string name;
   long handle = FileFindFirst(SubDir + "\\*.req", name);
   if(handle == INVALID_HANDLE)
      return;
   do
     {
      int sz = ArraySize(names);
      ArrayResize(names, sz + 1);
      names[sz] = name;
     }
   while(FileFindNext(handle, name));
   FileFindClose(handle);

   for(int i = 0; i < ArraySize(names); i++)
      ProcessRequest(names[i]);
  }
//+------------------------------------------------------------------+
