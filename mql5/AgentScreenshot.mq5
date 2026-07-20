//+------------------------------------------------------------------+
//| AgentScreenshot.mq5                                              |
//| File-bridge EA for mt5-trading-mcp get_chart_screenshot.         |
//| Polls MQL5/Files/agent_screenshot/*.req, opens the requested     |
//| chart, draws any annotation lines, calls ChartScreenShot(), and  |
//| writes <id>.png + <id>.done. Annotations live only on the        |
//| temporary chart, so ChartClose discards them.                    |
//| Pairs with src/mt5_mcp/adapter/screenshot.py.                    |
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

//+------------------------------------------------------------------+
//| Annotation drawing. All objects live on the temporary chart the  |
//| request opened, so ChartClose destroys them; there is no state   |
//| to clean up between requests.                                    |
//+------------------------------------------------------------------+
void MakeTextLabel(const long cid, const string name, const datetime t,
                   const double p, const string txt, const color clr,
                   const ENUM_ANCHOR_POINT anchor)
  {
   // MT5 renders OBJPROP_TEXT on HLINE/VLINE/TREND as a tooltip only, never
   // on the chart surface, so a labelled line needs a companion OBJ_TEXT.
   if(!ObjectCreate(cid, name, OBJ_TEXT, 0, t, p))
      return;
   ObjectSetString(cid, name, OBJPROP_TEXT, txt);
   ObjectSetInteger(cid, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(cid, name, OBJPROP_ANCHOR, anchor);
   ObjectSetInteger(cid, name, OBJPROP_FONTSIZE, 9);
   ObjectSetInteger(cid, name, OBJPROP_SELECTABLE, false);
  }

void StyleLine(const long cid, const string name, const color clr, const int style)
  {
   ObjectSetInteger(cid, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(cid, name, OBJPROP_STYLE, style);
   ObjectSetInteger(cid, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(cid, name, OBJPROP_BACK, false);
   ObjectSetInteger(cid, name, OBJPROP_SELECTABLE, false);
  }

void DrawAnnotations(const long cid, const string symbol, const ENUM_TIMEFRAMES tf,
                     const string reqId, const string &lines[])
  {
   // The chart was just opened, so it is scrolled to the right edge and bar 0
   // is the rightmost visible bar. That is where hline labels are anchored.
   datetime rightEdge = iTime(symbol, tf, 0);
   double   priceMax  = ChartGetDouble(cid, CHART_PRICE_MAX, 0);

   for(int i = 0; i < ArraySize(lines); i++)
     {
      string f[];
      int n = StringSplit(lines[i], '|', f);
      if(n < 2 || f[0] != "A")
         continue;

      string kind  = f[1];
      string oname = "agent_" + reqId + "_" + IntegerToString(i);
      string lname = oname + "_lbl";

      if(kind == "hline" && n >= 6)
        {
         double price = StringToDouble(f[2]);
         color  clr   = (color)StringToInteger(f[3]);
         int    style = (int)StringToInteger(f[4]);
         if(ObjectCreate(cid, oname, OBJ_HLINE, 0, 0, price))
           {
            StyleLine(cid, oname, clr, style);
            if(StringLen(f[5]) > 0)
               MakeTextLabel(cid, lname, rightEdge, price, f[5], clr,
                             ANCHOR_RIGHT_LOWER);
           }
        }
      else if(kind == "vline" && n >= 6)
        {
         datetime t     = (datetime)StringToInteger(f[2]);
         color    clr   = (color)StringToInteger(f[3]);
         int      style = (int)StringToInteger(f[4]);
         if(ObjectCreate(cid, oname, OBJ_VLINE, 0, t, 0))
           {
            StyleLine(cid, oname, clr, style);
            if(StringLen(f[5]) > 0)
               MakeTextLabel(cid, lname, t, priceMax, f[5], clr,
                             ANCHOR_LEFT_UPPER);
           }
        }
      else if(kind == "text" && n >= 6)
        {
         datetime t     = (datetime)StringToInteger(f[2]);
         double   price = StringToDouble(f[3]);
         color    clr   = (color)StringToInteger(f[4]);
         MakeTextLabel(cid, oname, t, price, f[5], clr, ANCHOR_LEFT_LOWER);
        }
      else if(kind == "label" && n >= 7)
        {
         int   corner = (int)StringToInteger(f[2]);
         int   xd     = (int)StringToInteger(f[3]);
         int   yd     = (int)StringToInteger(f[4]);
         color clr    = (color)StringToInteger(f[5]);
         if(ObjectCreate(cid, oname, OBJ_LABEL, 0, 0, 0))
           {
            ObjectSetInteger(cid, oname, OBJPROP_CORNER, corner);
            ObjectSetInteger(cid, oname, OBJPROP_XDISTANCE, xd);
            ObjectSetInteger(cid, oname, OBJPROP_YDISTANCE, yd);
            ObjectSetString(cid, oname, OBJPROP_TEXT, f[6]);
            ObjectSetInteger(cid, oname, OBJPROP_COLOR, clr);
            ObjectSetInteger(cid, oname, OBJPROP_FONTSIZE, 9);
            ObjectSetInteger(cid, oname, OBJPROP_SELECTABLE, false);
           }
        }
      else if(kind == "trend" && n >= 9)
        {
         datetime t1    = (datetime)StringToInteger(f[2]);
         double   p1    = StringToDouble(f[3]);
         datetime t2    = (datetime)StringToInteger(f[4]);
         double   p2    = StringToDouble(f[5]);
         color    clr   = (color)StringToInteger(f[6]);
         int      style = (int)StringToInteger(f[7]);
         if(ObjectCreate(cid, oname, OBJ_TREND, 0, t1, p1, t2, p2))
           {
            StyleLine(cid, oname, clr, style);
            ObjectSetInteger(cid, oname, OBJPROP_RAY_RIGHT, false);
            if(StringLen(f[8]) > 0)
               MakeTextLabel(cid, lname, t2, p2, f[8], clr, ANCHOR_LEFT_LOWER);
           }
        }
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
   string annLines[];
   while(!FileIsEnding(h))
     {
      string ln = FileReadString(h);
      if(StringLen(ln) == 0)
         continue;
      int asz = ArraySize(annLines);
      ArrayResize(annLines, asz + 1);
      annLines[asz] = ln;
     }
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

   DrawAnnotations(cid, symbol, tf, id, annLines);
   ChartRedraw(cid);
   Sleep(SettleMs);

   string pngPath = SubDir + "\\" + id + ".png";
   bool ok = ChartScreenShot(cid, pngPath, width, height, ALIGN_RIGHT);
   // Belt and braces: ChartClose already destroys chart-scoped objects.
   ObjectsDeleteAll(cid);
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
