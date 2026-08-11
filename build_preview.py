# -*- coding: utf-8 -*-
"""Builds preview.html: a single self-contained demo copy of the landing.

Images are inlined as data URIs and the booking API is replaced by an in-page
mock, so the whole flow (calendar, price, confirmation screen) can be tried
by opening one file. Marked as a demo so nobody mistakes it for production.
Run: py -3 build_preview.py
"""
import base64
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "index.html")
OUT = os.path.join(ROOT, "preview.html")
PHOTOS = os.path.join(ROOT, "photos")

MOCK = """
<style>
  .demo-flag{
    position:fixed;left:14px;bottom:14px;z-index:70;
    background:rgba(20,19,17,.86);border:1px solid #2c2823;color:#a59c8c;
    border-radius:999px;padding:7px 15px;font:500 12.5px/1 "Golos Text",sans-serif;
    letter-spacing:.03em;pointer-events:none;
  }
  @media(max-width:767px){.demo-flag{bottom:78px}}
</style>
<script>
/* Локальная заглушка бронирования: даёт потрогать весь путь гостя
   без сервера. В рабочей версии сайта этого кода нет. */
(function(){
  var busy = [], counter = 0, realFetch = window.fetch;
  var d = new Date(); d.setHours(0,0,0,0);
  function ymd(x){var m=x.getMonth()+1,day=x.getDate();return x.getFullYear()+"-"+(m<10?"0":"")+m+"-"+(day<10?"0":"")+day;}
  /* пара занятых дат, чтобы было видно, как выглядит "занято" */
  [3, 9].forEach(function(offset){
    var t = new Date(d); t.setDate(t.getDate()+offset); busy.push(ymd(t));
  });
  function reply(obj){
    return Promise.resolve({ok:true, json:function(){return Promise.resolve(obj);}});
  }
  window.fetch = function(url, opts){
    url = String(url);
    if(url.indexOf("/api") === -1) return realFetch.apply(this, arguments);
    if(url.indexOf("action=availability") !== -1) return reply({ok:true, busy:busy, blocked:[]});
    var body = {};
    try { body = JSON.parse((opts && opts.body) || "{}"); } catch(e){}
    if(body.action === "book"){
      if(busy.indexOf(body.date) !== -1) return reply({ok:false, error:"date_taken"});
      busy.push(body.date);
      counter++;
      return new Promise(function(res){
        setTimeout(function(){
          res({ok:true, json:function(){return Promise.resolve({ok:true, id:"TM-"+("000"+counter).slice(-4)});}});
        }, 450);
      });
    }
    return reply({ok:false, error:"demo"});
  };
  document.addEventListener("DOMContentLoaded", function(){
    var flag = document.createElement("div");
    flag.className = "demo-flag";
    flag.textContent = "Демо-копия: заявки никуда не уходят";
    document.body.appendChild(flag);
  });
})();
</script>
"""


def data_uri(name):
    path = os.path.join(PHOTOS, name)
    with open(path, "rb") as fh:
        return "data:image/jpeg;base64," + base64.b64encode(fh.read()).decode("ascii")


def main():
    with open(SRC, "r", encoding="utf-8") as fh:
        html = fh.read()

    # Заглушку ставим на место config.js, то есть раньше кода бронирования,
    # иначе календарь успевает запросить занятые даты через настоящий fetch.
    # Адрес заведомо недостижимый, но с https, чтобы страница считала
    # бронирование настроенным. Все запросы к нему перехватывает заглушка,
    # поэтому демо работает и с диска, и на любом хостинге.
    html = html.replace('<script src="config.js"></script>',
                        '<script>window.BESEDKA_API="https://demo.invalid/api";</script>' + MOCK)

    inlined = []
    for name in sorted(os.listdir(PHOTOS)):
        if not name.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        needle = 'src="photos/%s"' % name
        if needle in html:
            html = html.replace(needle, 'src="%s"' % data_uri(name))
            inlined.append(name)

    # og:image ссылкой оставлять смысла нет в локальном файле
    html = re.sub(r'<meta property="og:image"[^>]*>\n?', "", html)

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(html)

    size = os.path.getsize(OUT) / 1024
    print("preview.html: %.0f KB, inlined %d images: %s" % (size, len(inlined), ", ".join(inlined)))
    leftover = re.findall(r'src="photos/[^"]+"', html)
    print("not inlined:", leftover if leftover else "none")


if __name__ == "__main__":
    main()
