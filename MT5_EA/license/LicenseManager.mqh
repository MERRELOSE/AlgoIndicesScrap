//+------------------------------------------------------------------+
//|                                              LicenseManager.mqh  |
//|                         License & Subscription Management        |
//|                         Protects EA with account binding + expiry |
//+------------------------------------------------------------------+
#property copyright "AlgoIndicesScrap"
#property strict

// ============================================================
// SECRET KEY - Change this to YOUR unique secret
// This is embedded in the compiled .ex5 and not visible
// ============================================================
#define LICENSE_SECRET "AIS_X7k9Pm2vR4tQ8wL5nJ6yB3cF1dH0"

// ============================================================
// LICENSE STATUS
// ============================================================
enum LICENSE_STATUS
{
   LICENSE_VALID,
   LICENSE_EXPIRED,
   LICENSE_WRONG_ACCOUNT,
   LICENSE_INVALID_KEY,
   LICENSE_NOT_SET
};

// ============================================================
// Generate hash from account + expiry + secret
// Simple but effective for .ex5 distribution
// ============================================================
string GenerateHash(long accountNumber, string expiryDate)
{
   // Combine: account + expiry + secret
   string raw = IntegerToString(accountNumber) + expiryDate + LICENSE_SECRET;

   // Simple hash algorithm (good enough for compiled .ex5)
   ulong hash1 = 5381;
   ulong hash2 = 52711;

   for(int i = 0; i < StringLen(raw); i++)
   {
      ushort c = StringGetCharacter(raw, i);
      hash1 = ((hash1 << 5) + hash1) ^ c;
      hash2 = ((hash2 << 5) + hash2) ^ c;
   }

   // Convert to hex string
   string result = "";
   ulong combined = hash1 * 31 + hash2;

   // Create readable license key format: XXXX-XXXX-XXXX-XXXX
   string hex = "";
   for(int i = 0; i < 16; i++)
   {
      int digit = (int)(combined % 36);
      combined /= 36;
      if(digit < 10)
         hex += IntegerToString(digit);
      else
         hex += CharToString((char)('A' + digit - 10));
   }

   result = StringSubstr(hex, 0, 4) + "-" +
            StringSubstr(hex, 4, 4) + "-" +
            StringSubstr(hex, 8, 4) + "-" +
            StringSubstr(hex, 12, 4);

   return result;
}

// ============================================================
// Parse expiry date string (YYYY.MM.DD) to datetime
// ============================================================
datetime ParseExpiryDate(string dateStr)
{
   // Expected format: YYYY.MM.DD
   if(StringLen(dateStr) < 10) return 0;

   int year = (int)StringToInteger(StringSubstr(dateStr, 0, 4));
   int month = (int)StringToInteger(StringSubstr(dateStr, 5, 2));
   int day = (int)StringToInteger(StringSubstr(dateStr, 8, 2));

   MqlDateTime dt;
   dt.year = year;
   dt.mon = month;
   dt.day = day;
   dt.hour = 23;
   dt.min = 59;
   dt.sec = 59;

   return StructToTime(dt);
}

// ============================================================
// MAIN VALIDATION FUNCTION
// ============================================================
LICENSE_STATUS ValidateLicense(string licenseKey, long allowedAccount, string expiryDateStr)
{
   // 1. Check if license key is set
   if(StringLen(licenseKey) < 10)
      return LICENSE_NOT_SET;

   // 2. Check account number
   long currentAccount = AccountInfoInteger(ACCOUNT_LOGIN);
   if(currentAccount != allowedAccount)
      return LICENSE_WRONG_ACCOUNT;

   // 3. Check expiry
   datetime expiryTime = ParseExpiryDate(expiryDateStr);
   if(expiryTime == 0)
      return LICENSE_INVALID_KEY;

   if(TimeCurrent() > expiryTime)
      return LICENSE_EXPIRED;

   // 4. Verify license key hash
   string expectedKey = GenerateHash(allowedAccount, expiryDateStr);
   if(licenseKey != expectedKey)
      return LICENSE_INVALID_KEY;

   return LICENSE_VALID;
}

// ============================================================
// Days remaining until expiry
// ============================================================
int DaysRemaining(string expiryDateStr)
{
   datetime expiryTime = ParseExpiryDate(expiryDateStr);
   if(expiryTime == 0) return -1;

   int seconds = (int)(expiryTime - TimeCurrent());
   return seconds / 86400;
}

// ============================================================
// Display license status on chart
// ============================================================
void ShowLicenseStatus(LICENSE_STATUS status, string expiryDateStr, int daysLeft)
{
   string objName = "LICENSE_STATUS";

   // Delete old object
   ObjectDelete(0, objName);
   ObjectDelete(0, objName + "_2");
   ObjectDelete(0, objName + "_3");

   string text1 = "";
   string text2 = "";
   color textColor = clrWhite;

   switch(status)
   {
      case LICENSE_VALID:
         if(daysLeft <= 7)
         {
            text1 = "LICENSE: EXPIRES IN " + IntegerToString(daysLeft) + " DAYS!";
            text2 = "Renew now to continue trading";
            textColor = clrOrange;
         }
         else if(daysLeft <= 14)
         {
            text1 = "LICENSE: " + IntegerToString(daysLeft) + " days remaining";
            text2 = "Consider renewing soon";
            textColor = clrYellow;
         }
         else
         {
            text1 = "LICENSE: Active until " + expiryDateStr;
            text2 = IntegerToString(daysLeft) + " days remaining";
            textColor = clrLime;
         }
         break;

      case LICENSE_EXPIRED:
         text1 = "LICENSE EXPIRED on " + expiryDateStr;
         text2 = "Contact admin to renew. EA DISABLED.";
         textColor = clrRed;
         break;

      case LICENSE_WRONG_ACCOUNT:
         text1 = "LICENSE ERROR: Wrong trading account";
         text2 = "This license is not valid for account " +
                 IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
         textColor = clrRed;
         break;

      case LICENSE_INVALID_KEY:
         text1 = "LICENSE ERROR: Invalid license key";
         text2 = "Contact admin for a valid license";
         textColor = clrRed;
         break;

      case LICENSE_NOT_SET:
         text1 = "NO LICENSE - EA DISABLED";
         text2 = "Enter your license key in EA settings";
         textColor = clrRed;
         break;
   }

   // Create text labels on chart
   ObjectCreate(0, objName, OBJ_LABEL, 0, 0, 0);
   ObjectSetString(0, objName, OBJPROP_TEXT, text1);
   ObjectSetInteger(0, objName, OBJPROP_XDISTANCE, 10);
   ObjectSetInteger(0, objName, OBJPROP_YDISTANCE, 30);
   ObjectSetInteger(0, objName, OBJPROP_COLOR, textColor);
   ObjectSetInteger(0, objName, OBJPROP_FONTSIZE, 12);
   ObjectSetString(0, objName, OBJPROP_FONT, "Arial Bold");
   ObjectSetInteger(0, objName, OBJPROP_CORNER, CORNER_LEFT_UPPER);

   ObjectCreate(0, objName + "_2", OBJ_LABEL, 0, 0, 0);
   ObjectSetString(0, objName + "_2", OBJPROP_TEXT, text2);
   ObjectSetInteger(0, objName + "_2", OBJPROP_XDISTANCE, 10);
   ObjectSetInteger(0, objName + "_2", OBJPROP_YDISTANCE, 50);
   ObjectSetInteger(0, objName + "_2", OBJPROP_COLOR, textColor);
   ObjectSetInteger(0, objName + "_2", OBJPROP_FONTSIZE, 10);
   ObjectSetString(0, objName + "_2", OBJPROP_FONT, "Arial");
   ObjectSetInteger(0, objName + "_2", OBJPROP_CORNER, CORNER_LEFT_UPPER);
}

// ============================================================
// Send alert for expiring license
// ============================================================
void CheckExpiryAlerts(int daysLeft, string expiryDateStr)
{
   static datetime lastAlert = 0;
   datetime now = TimeCurrent();

   // Alert once per day max
   if(now - lastAlert < 86400) return;

   if(daysLeft == 7 || daysLeft == 3 || daysLeft == 1)
   {
      Alert("CrashHunter EA - License expires in ", daysLeft, " day(s)! Expiry: ", expiryDateStr);
      Print("LICENSE WARNING: ", daysLeft, " days remaining. Renew to continue trading.");
      lastAlert = now;
   }

   if(daysLeft <= 0)
   {
      Alert("CrashHunter EA - LICENSE EXPIRED! Trading disabled. Contact admin to renew.");
      lastAlert = now;
   }
}
//+------------------------------------------------------------------+
