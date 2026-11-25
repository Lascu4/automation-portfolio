/**
 * Google Sheets Sales & Inventory Automation (Apps Script)
 *
 * What it does:
 *  - Adds a custom "Automation" menu to the spreadsheet.
 *  - Builds a daily sales summary (revenue, units, top products) in a "Report" sheet.
 *  - Flags low-stock products and emails an alert (optional, daily trigger).
 *  - Cleans the raw "Sales" sheet: trims text, removes blank rows and exact duplicates.
 *
 * Expected sheets:
 *  Sales:     Date | Order ID | SKU | Product | Qty | Unit Price
 *  Inventory: SKU  | Product  | Stock | Min Stock
 *
 * Setup: Extensions > Apps Script > paste this file > Save > reload the sheet.
 * Run "Automation > Install daily trigger" once to schedule the alert at 8 AM.
 */

const CONFIG = {
  salesSheet: 'Sales',
  inventorySheet: 'Inventory',
  reportSheet: 'Report',
  alertEmail: '', // leave empty to send to the spreadsheet owner
  topN: 5,
};

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Automation')
    .addItem('Clean sales data', 'cleanSalesData')
    .addItem('Build sales report', 'buildReport')
    .addItem('Check low stock now', 'checkLowStock')
    .addSeparator()
    .addItem('Install daily trigger', 'installDailyTrigger')
    .addToUi();
}

function getSheet_(name) {
  const sheet = SpreadsheetApp.getActive().getSheetByName(name);
  if (!sheet) throw new Error('Missing sheet: ' + name);
  return sheet;
}

/** Trim text, drop empty rows and exact duplicates in the Sales sheet. */
function cleanSalesData() {
  const sheet = getSheet_(CONFIG.salesSheet);
  const values = sheet.getDataRange().getValues();
  const header = values.shift();
  const seen = new Set();
  const cleaned = [];

  values.forEach(function (row) {
    const r = row.map(function (v) { return typeof v === 'string' ? v.trim() : v; });
    if (r.every(function (v) { return v === '' || v === null; })) return;
    const key = JSON.stringify(r);
    if (seen.has(key)) return;
    seen.add(key);
    cleaned.push(r);
  });

  const removed = values.length - cleaned.length;
  sheet.getRange(2, 1, Math.max(sheet.getLastRow() - 1, 1), header.length).clearContent();
  if (cleaned.length) sheet.getRange(2, 1, cleaned.length, header.length).setValues(cleaned);
  SpreadsheetApp.getActive().toast(removed + ' rows removed', 'Clean sales data');
}

/** Summarise revenue and units per day and list the top products. */
function buildReport() {
  const rows = getSheet_(CONFIG.salesSheet).getDataRange().getValues().slice(1);
  const tz = Session.getScriptTimeZone();
  const byDay = {};
  const byProduct = {};
  let totalRevenue = 0;
  let totalUnits = 0;

  rows.forEach(function (r) {
    const date = r[0], product = r[3], qty = Number(r[4]) || 0, price = Number(r[5]) || 0;
    if (!date || !qty) return;
    const day = Utilities.formatDate(new Date(date), tz, 'yyyy-MM-dd');
    const revenue = qty * price;
    byDay[day] = byDay[day] || { units: 0, revenue: 0 };
    byDay[day].units += qty;
    byDay[day].revenue += revenue;
    byProduct[product] = (byProduct[product] || 0) + revenue;
    totalRevenue += revenue;
    totalUnits += qty;
  });

  const ss = SpreadsheetApp.getActive();
  const report = ss.getSheetByName(CONFIG.reportSheet) || ss.insertSheet(CONFIG.reportSheet);
  report.clear();

  report.getRange('A1').setValue('Sales report').setFontSize(14).setFontWeight('bold');
  report.getRange('A2').setValue('Updated: ' + Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd HH:mm'));
  report.getRange('A4:B5').setValues([
    ['Total revenue', totalRevenue],
    ['Total units', totalUnits],
  ]);

  const days = Object.keys(byDay).sort().map(function (d) {
    return [d, byDay[d].units, byDay[d].revenue];
  });
  report.getRange('A7:C7').setValues([['Date', 'Units', 'Revenue']]).setFontWeight('bold');
  if (days.length) report.getRange(8, 1, days.length, 3).setValues(days);

  const top = Object.keys(byProduct)
    .map(function (p) { return [p, byProduct[p]]; })
    .sort(function (a, b) { return b[1] - a[1]; })
    .slice(0, CONFIG.topN);
  report.getRange('E7:F7').setValues([['Top products', 'Revenue']]).setFontWeight('bold');
  if (top.length) report.getRange(8, 5, top.length, 2).setValues(top);

  report.getRange('B4').setNumberFormat('$#,##0.00');
  report.getRange('C8:C').setNumberFormat('$#,##0.00');
  report.getRange('F8:F').setNumberFormat('$#,##0.00');
  report.autoResizeColumns(1, 6);

  if (days.length) {
    const chart = report.newChart()
      .setChartType(Charts.ChartType.COLUMN)
      .addRange(report.getRange(7, 1, days.length + 1, 1))
      .addRange(report.getRange(7, 3, days.length + 1, 1))
      .setPosition(4, 8, 0, 0)
      .setOption('title', 'Revenue per day')
      .setOption('legend', { position: 'none' })
      .build();
    report.insertChart(chart);
  }
}

/** Highlight products under their minimum stock and email a summary. */
function checkLowStock() {
  const sheet = getSheet_(CONFIG.inventorySheet);
  const range = sheet.getDataRange();
  const values = range.getValues();
  const low = [];

  range.offset(1, 0, Math.max(values.length - 1, 1)).setBackground(null);
  for (let i = 1; i < values.length; i++) {
    const sku = values[i][0], product = values[i][1];
    const stock = Number(values[i][2]), min = Number(values[i][3]);
    if (sku !== '' && stock <= min) {
      low.push(product + ' (' + sku + '): ' + stock + ' left, minimum ' + min);
      sheet.getRange(i + 1, 1, 1, values[i].length).setBackground('#F8D7DA');
    }
  }

  if (!low.length) return;
  const to = CONFIG.alertEmail || Session.getEffectiveUser().getEmail();
  MailApp.sendEmail({
    to: to,
    subject: 'Low stock alert: ' + low.length + ' product(s)',
    body: 'These products are at or below minimum stock:\n\n- ' + low.join('\n- ') +
      '\n\nSheet: ' + SpreadsheetApp.getActive().getUrl(),
  });
}

/** Daily job: rebuild the report and check stock. */
function dailyJob() {
  buildReport();
  checkLowStock();
}

function installDailyTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === 'dailyJob'; })
    .forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('dailyJob').timeBased().everyDays(1).atHour(8).create();
  SpreadsheetApp.getActive().toast('Daily job scheduled at 8 AM', 'Automation');
}
