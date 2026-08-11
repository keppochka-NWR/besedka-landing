/**
 * Бэкенд бронирования «Тёплое место» на Google Apps Script.
 * Хранит заявки в Google-таблице, шлёт уведомление менеджеру в Telegram и на почту.
 * Контракт API совпадает с dev_server.py, поэтому фронтенд не меняется.
 *
 * Настройка: Расширения → Apps Script в новой Google-таблице,
 * вставить этот код, заполнить CONFIG, затем Развернуть → Веб-приложение
 * (доступ: «Все»), скопировать URL в index.html и admin.html.
 */

var CONFIG = {
  ADMIN_TOKEN: 'СМЕНИТЕ_ЭТОТ_ПАРОЛЬ',     // пароль для входа в админку
  MANAGER_EMAIL: '',                       // почта менеджера, можно оставить пустой
  TELEGRAM_BOT_TOKEN: '',                  // токен бота от @BotFather
  TELEGRAM_CHAT_ID: '',                    // id чата менеджера (узнать у @userinfobot)
  SHEET_BOOKINGS: 'Брони',
  SHEET_BLOCKED: 'Закрытые даты'
};

var HEADERS = ['ID', 'Создана', 'Дата', 'Тариф', 'Тариф (текст)', 'С', 'До',
               'Часов', 'Гостей', 'Цена', 'Имя', 'Телефон', 'Комментарий', 'Статус'];

// ---------- служебное ----------

function sheet_(name, headers) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(name);
  if (!sh) {
    sh = ss.insertSheet(name);
    if (headers) sh.appendRow(headers);
    sh.setFrozenRows(1);
  }
  return sh;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function str_(v, limit) {
  return String(v == null ? '' : v).trim().slice(0, limit || 300);
}

function isDate_(s) {
  return /^\d{4}-\d{2}-\d{2}$/.test(s);
}

function readBookings_() {
  var sh = sheet_(CONFIG.SHEET_BOOKINGS, HEADERS);
  var values = sh.getDataRange().getValues();
  var out = [];
  for (var i = 1; i < values.length; i++) {
    var r = values[i];
    if (!r[0]) continue;
    out.push({
      row: i + 1, id: str_(r[0]), created: str_(r[1]), date: str_(r[2]),
      tariff: str_(r[3]), tariffLabel: str_(r[4]), timeFrom: str_(r[5]), timeTo: str_(r[6]),
      hours: Number(r[7]) || 0, guests: Number(r[8]) || 0, price: Number(r[9]) || 0,
      name: str_(r[10]), phone: str_(r[11]), comment: str_(r[12]), status: str_(r[13]) || 'new'
    });
  }
  return out;
}

function readBlocked_() {
  var sh = sheet_(CONFIG.SHEET_BLOCKED, ['Дата', 'Причина']);
  var values = sh.getDataRange().getValues();
  var out = [];
  for (var i = 1; i < values.length; i++) {
    var d = str_(values[i][0], 10);
    if (isDate_(d)) out.push(d);
  }
  return out;
}

function busyDates_(bookings) {
  var seen = {}, out = [];
  bookings.forEach(function (b) {
    if ((b.status === 'new' || b.status === 'confirmed') && !seen[b.date]) {
      seen[b.date] = true;
      out.push(b.date);
    }
  });
  return out.sort();
}

function notify_(booking) {
  var lines = [
    'Новая заявка на беседку',
    'Номер: ' + booking.id,
    'Дата: ' + booking.date,
    'Время: ' + booking.timeFrom + ' - ' + booking.timeTo + ' (' + booking.hours + ' ч)',
    'Тариф: ' + booking.tariffLabel,
    'Гостей: ' + booking.guests,
    'Сумма: ' + booking.price + ' руб',
    'Имя: ' + booking.name,
    'Телефон: ' + booking.phone
  ];
  if (booking.comment) lines.push('Комментарий: ' + booking.comment);
  lines.push('', 'Позвоните гостю и подтвердите дату.');
  var text = lines.join('\n');

  if (CONFIG.TELEGRAM_BOT_TOKEN && CONFIG.TELEGRAM_CHAT_ID) {
    try {
      UrlFetchApp.fetch('https://api.telegram.org/bot' + CONFIG.TELEGRAM_BOT_TOKEN + '/sendMessage', {
        method: 'post',
        payload: { chat_id: CONFIG.TELEGRAM_CHAT_ID, text: text },
        muteHttpExceptions: true
      });
    } catch (err) {
      console.error('telegram: ' + err);
    }
  }
  if (CONFIG.MANAGER_EMAIL) {
    try {
      MailApp.sendEmail(CONFIG.MANAGER_EMAIL, 'Заявка ' + booking.id + ' на ' + booking.date, text);
    } catch (err) {
      console.error('mail: ' + err);
    }
  }
}

// ---------- точки входа ----------

function doGet(e) {
  var p = (e && e.parameter) || {};
  if (p.action === 'availability') {
    return json_({ ok: true, busy: busyDates_(readBookings_()), blocked: readBlocked_() });
  }
  if (p.action === 'list') {
    if (str_(p.token, 60) !== CONFIG.ADMIN_TOKEN) return json_({ ok: false, error: 'auth' });
    var items = readBookings_().sort(function (a, b) {
      return a.date === b.date ? (a.created < b.created ? -1 : 1) : (a.date < b.date ? -1 : 1);
    });
    return json_({ ok: true, items: items, blocked: readBlocked_() });
  }
  return json_({ ok: false, error: 'unknown_action' });
}

function doPost(e) {
  var data = {};
  try {
    data = JSON.parse((e && e.postData && e.postData.contents) || '{}');
  } catch (err) {
    return json_({ ok: false, error: 'bad_json' });
  }

  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    if (data.action === 'book') return book_(data);

    if (str_(data.token, 60) !== CONFIG.ADMIN_TOKEN) return json_({ ok: false, error: 'auth' });
    if (data.action === 'status') return setStatus_(data);
    if (data.action === 'block' || data.action === 'unblock') return setBlocked_(data);
    return json_({ ok: false, error: 'unknown_action' });
  } finally {
    lock.releaseLock();
  }
}

function book_(data) {
  var date = str_(data.date, 10);
  var name = str_(data.name, 80);
  var phone = str_(data.phone, 30);
  var digits = phone.replace(/\D/g, '');

  if (!isDate_(date)) return json_({ ok: false, error: 'bad_date' });
  if (name.length < 2) return json_({ ok: false, error: 'bad_name' });
  if (digits.length < 10 || digits.length > 15) return json_({ ok: false, error: 'bad_phone' });

  var bookings = readBookings_();
  if (busyDates_(bookings).indexOf(date) !== -1 || readBlocked_().indexOf(date) !== -1) {
    return json_({ ok: false, error: 'date_taken' });
  }

  var sh = sheet_(CONFIG.SHEET_BOOKINGS, HEADERS);
  var id = 'TM-' + ('0000' + (bookings.length + 1)).slice(-4);
  var booking = {
    id: id,
    created: Utilities.formatDate(new Date(), 'Europe/Moscow', 'yyyy-MM-dd HH:mm:ss'),
    date: date,
    tariff: str_(data.tariff, 20),
    tariffLabel: str_(data.tariffLabel, 60),
    timeFrom: str_(data.timeFrom, 5),
    timeTo: str_(data.timeTo, 5),
    hours: Number(data.hours) || 0,
    guests: Number(data.guests) || 0,
    price: Number(data.price) || 0,
    name: name,
    phone: phone,
    comment: str_(data.comment, 500),
    status: 'new'
  };

  sh.appendRow([booking.id, booking.created, booking.date, booking.tariff, booking.tariffLabel,
                booking.timeFrom, booking.timeTo, booking.hours, booking.guests, booking.price,
                booking.name, booking.phone, booking.comment, booking.status]);

  notify_(booking);
  return json_({ ok: true, id: booking.id });
}

function setStatus_(data) {
  var allowed = ['new', 'confirmed', 'cancelled'];
  var status = str_(data.status, 20);
  if (allowed.indexOf(status) === -1) return json_({ ok: false, error: 'bad_status' });

  var sh = sheet_(CONFIG.SHEET_BOOKINGS, HEADERS);
  var bookings = readBookings_();
  for (var i = 0; i < bookings.length; i++) {
    if (bookings[i].id === str_(data.id, 20)) {
      sh.getRange(bookings[i].row, HEADERS.length).setValue(status);
      return json_({ ok: true });
    }
  }
  return json_({ ok: false, error: 'not_found' });
}

function setBlocked_(data) {
  var date = str_(data.date, 10);
  if (!isDate_(date)) return json_({ ok: false, error: 'bad_date' });

  var sh = sheet_(CONFIG.SHEET_BLOCKED, ['Дата', 'Причина']);
  if (data.action === 'block') {
    if (readBlocked_().indexOf(date) === -1) sh.appendRow([date, str_(data.reason, 100)]);
    return json_({ ok: true });
  }

  var values = sh.getDataRange().getValues();
  for (var i = values.length - 1; i >= 1; i--) {
    if (str_(values[i][0], 10) === date) sh.deleteRow(i + 1);
  }
  return json_({ ok: true });
}
