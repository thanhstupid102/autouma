'use strict';
// Native (OS-level) HTTP URL capture -- consumed by scripts/capture_native_urls.py.
//
// The IL2CPP hooks in integrations/frida/js/uma_full_traffic.js only see the
// game's own API traffic; the resource downloader fetches the manifest tree
// outside them. This hook therefore touches NO game code at all -- it taps the
// Windows HTTP stacks the downloader would have to use if it is not linking a
// TLS/HTTP client statically:
//
//   winhttp.dll  WinHttpConnect / WinHttpOpenRequest / WinHttpSendRequest
//   wininet.dll  InternetConnectW|A / HttpOpenRequestW|A / HttpSendRequestW|A
//                InternetOpenUrlW|A  (full URL in one argument)
//   ws2_32.dll   getaddrinfo / GetAddrInfoW / GetAddrInfoExW  (host-only signal)
//   any module   curl_easy_setopt(handle, CURLOPT_URL, char*)
//
// Goal: a full URL containing root.manifest.bsv.lz4?r= . WinHTTP/WinINet split
// that across two calls (host+port at connect time, verb+object path at request
// time), so connect handles are remembered and the URL is reassembled at
// request time, with the scheme taken from the *_FLAG_SECURE request flag.
//
// Payload contract -- exactly these 7 keys, and nothing else is ever sent:
//   {type: 'http', api: <string>, url: <string>, host: <string>,
//    path: <string>, module: <string>, port: <number|null>}
// The consumer drops any payload whose type is not 'http', so every diagnostic
// goes to console.log instead (frida-python surfaces those separately).
//
// Every export is resolved defensively and every hook is installed inside a
// try/catch: a stack the game never loads is skipped silently, and one bad
// hook can never take the others down. Modules can be loaded lazily, so the
// install pass repeats on a timer until every target is hooked.
(function () {
  var WINHTTP_FLAG_SECURE = 0x00800000;   // == INTERNET_FLAG_SECURE
  var CURLOPT_URL = 10002;
  var MAX_HANDLES = 4096;                 // handle-map cap (no CloseHandle hook)
  var MAX_SEEN = 20000;                   // dedupe-set cap
  var SLOW_EVERY = 5;                     // module-wide scans: 1 attempt in 5
  var HINT_AFTER = 30;                    // attempts before the mitmproxy hint

  var seen = new Set();          // identity -> already sent (mirrors consumer)
  var traced = new Set();        // api + identity -> already logged
  var installed = {};            // label -> owning module name
  var installedCount = 0;
  var attempts = 0;
  var hinted = false;
  var connections = {};          // connect handle -> {host, port, module}
  var connectionCount = 0;
  var requests = {};             // request handle -> emit payload fields
  var requestCount = 0;

  /* ---------------------------------------------------------------- utils */

  function isNullPtr(p) {
    if (p === null || p === undefined) return true;
    try {
      if (typeof p.isNull === 'function') return p.isNull();
    } catch (e) {}
    return false;
  }

  function readWide(p) {
    if (isNullPtr(p)) return '';
    try { return p.readUtf16String() || ''; } catch (e) { return ''; }
  }

  function readAnsi(p) {
    if (isNullPtr(p)) return '';
    try { return p.readAnsiString() || ''; } catch (e) { return ''; }
  }

  function readUtf8(p) {
    if (isNullPtr(p)) return '';
    try { return p.readUtf8String() || ''; } catch (e) {}
    try { return p.readCString() || ''; } catch (e2) {}
    return '';
  }

  function toUint(v) {
    if (v === null || v === undefined) return 0;
    try {
      if (typeof v.toUInt32 === 'function') return v.toUInt32() >>> 0;
    } catch (e) {}
    try {
      if (typeof v.toInt32 === 'function') return v.toInt32() >>> 0;
    } catch (e2) {}
    var n = Number(v);
    return isNaN(n) ? 0 : (n >>> 0);
  }

  function handleKey(p) {
    if (isNullPtr(p)) return '';
    try { return String(p); } catch (e) { return ''; }
  }

  function has(map, key) {
    return key !== '' && Object.prototype.hasOwnProperty.call(map, key);
  }

  function storeConnection(key, value) {
    if (!key) return;
    if (connectionCount >= MAX_HANDLES) { connections = {}; connectionCount = 0; }
    if (!has(connections, key)) connectionCount++;
    connections[key] = value;
  }

  function storeRequest(key, value) {
    if (!key) return;
    if (requestCount >= MAX_HANDLES) { requests = {}; requestCount = 0; }
    if (!has(requests, key)) requestCount++;
    requests[key] = value;
  }

  /* ------------------------------------------------------------ URL logic */

  function defaultPort(scheme) {
    return scheme === 'https' ? 443 : 80;
  }

  function normalizePath(path) {
    if (!path) return '/';
    return path.charAt(0) === '/' ? path : '/' + path;
  }

  // scheme + host + port + object path -> the URL the consumer greps.
  function buildUrl(scheme, host, port, path) {
    if (!host) return '';
    var authority = host;
    if (authority.indexOf(':') >= 0 && authority.charAt(0) !== '[') {
      authority = '[' + authority + ']';   // bare IPv6 literal
    }
    if (port && port !== defaultPort(scheme)) authority += ':' + port;
    return scheme + '://' + authority + normalizePath(path);
  }

  // Split a whole URL (InternetOpenUrl / CURLOPT_URL) back into the fields the
  // consumer stores. The query string stays on the path so `?r=` survives.
  function splitUrl(url) {
    var out = {scheme: '', host: '', path: '', port: null};
    if (!url) return out;
    var m = /^([a-zA-Z][a-zA-Z0-9+.\-]*):\/\/([^\/?#]*)([^#]*)/.exec(url);
    if (!m) return out;
    out.scheme = m[1].toLowerCase();
    out.path = normalizePath(m[3] || '');
    var authority = m[2] || '';
    var at = authority.lastIndexOf('@');
    if (at >= 0) authority = authority.substring(at + 1);
    if (authority.charAt(0) === '[') {
      var close = authority.indexOf(']');
      if (close > 0) {
        out.host = authority.substring(1, close);
        var rest = authority.substring(close + 1);
        if (rest.charAt(0) === ':') out.port = parseInt(rest.substring(1), 10);
      } else {
        out.host = authority;
      }
    } else {
      var colon = authority.lastIndexOf(':');
      if (colon >= 0) {
        out.host = authority.substring(0, colon);
        out.port = parseInt(authority.substring(colon + 1), 10);
      } else {
        out.host = authority;
      }
    }
    if (out.port === null || isNaN(out.port)) {
      out.port = (out.scheme === 'http' || out.scheme === 'https')
        ? defaultPort(out.scheme)
        : null;
    }
    return out;
  }

  /* -------------------------------------------------------------- emitter */

  function trace(api, identity, url, host, path) {
    try {
      var key = api + '\u0000' + identity;
      if (traced.has(key)) return;
      if (traced.size >= MAX_SEEN) traced.clear();
      traced.add(key);
      console.log('[native_http_urls] ' + api + ' ' +
        (url || ('host=' + host + ' path=' + path)));
    } catch (e) {}
  }

  function emit(api, info) {
    try {
      var url = info.url || '';
      var host = info.host || '';
      var path = info.path || '';
      // Same identity the consumer de-dupes on: url, else host + NUL + path.
      var identity = url || (host + '\u0000' + path);
      if (!identity || identity === '\u0000') return;
      trace(api, identity, url, host, path);
      if (seen.has(identity)) return;
      if (seen.size >= MAX_SEEN) seen.clear();
      seen.add(identity);
      var port = info.port;
      send({
        type: 'http',
        api: String(api),
        url: url,
        host: host,
        path: path,
        module: info.module || '',
        port: (typeof port === 'number' && isFinite(port)) ? port : null
      });
    } catch (e) {}
  }

  /* ------------------------------------------------------ export resolving */

  function moduleNameFor(address) {
    try {
      var mod = Process.findModuleByAddress(address);
      if (mod && mod.name) return mod.name;
    } catch (e) {}
    return '';
  }

  // Enumerated once per install pass: the loader's casing for a DLL is not
  // guaranteed, and a pass may need several by-name lookups.
  var passModules = null;

  function allModules() {
    if (passModules !== null) return passModules;
    try {
      passModules = Process.enumerateModules() || [];
    } catch (e) {
      passModules = [];
    }
    return passModules;
  }

  function moduleByName(moduleName) {
    try {
      var mod = Process.findModuleByName(moduleName);
      if (mod) return mod;
    } catch (e) {}
    var wanted = String(moduleName).toLowerCase();
    var modules = allModules();
    for (var i = 0; i < modules.length; i++) {
      try {
        if (modules[i] && String(modules[i].name).toLowerCase() === wanted) {
          return modules[i];
        }
      } catch (e2) {}
    }
    return null;
  }

  function resolveExport(moduleName, symbol) {
    var address = null;
    try {
      // Frida <= 16 static form; removed in Frida 17.
      if (typeof Module.findExportByName === 'function') {
        address = Module.findExportByName(moduleName, symbol);
      }
    } catch (e) { address = null; }
    if (isNullPtr(address) && moduleName === null) {
      try {
        // Frida >= 17 moved the whole-process lookup to its own entry point.
        if (typeof Module.findGlobalExportByName === 'function') {
          address = Module.findGlobalExportByName(symbol);
        }
      } catch (e2) { address = null; }
    }
    if (isNullPtr(address) && moduleName !== null) {
      try {
        var mod = moduleByName(moduleName);
        if (mod && typeof mod.findExportByName === 'function') {
          address = mod.findExportByName(symbol);
        }
      } catch (e3) { address = null; }
    }
    return isNullPtr(address) ? null : address;
  }

  // libcurl may be bundled under any name, so fall back to a module sweep.
  function findExportAnywhere(symbol) {
    var address = resolveExport(null, symbol);
    if (address) return address;
    var modules = allModules();
    for (var i = 0; i < modules.length; i++) {
      try {
        var mod = modules[i];
        if (!mod || typeof mod.findExportByName !== 'function') continue;
        var found = mod.findExportByName(symbol);
        if (!isNullPtr(found)) return found;
      } catch (e) {}
    }
    return null;
  }

  function install(target) {
    if (has(installed, target.label)) return true;
    var address;
    try {
      address = target.module === '*'
        ? findExportAnywhere(target.symbol)
        : resolveExport(target.module, target.symbol);
    } catch (e) { address = null; }
    if (!address) return false;          // not loaded (yet) -- retry later
    var owner = moduleNameFor(address) || (target.module === '*' ? '' : target.module);
    try {
      Interceptor.attach(address, target.make(owner));
    } catch (e) {
      // A hook that refuses to install must not stop the remaining ones.
      console.log('[native_http_urls] could not hook ' + target.symbol + ': ' + e);
      installed[target.label] = 'failed';
      return true;
    }
    installed[target.label] = owner || target.symbol;
    installedCount++;
    console.log('[native_http_urls] hooked ' + target.symbol +
      (owner ? ' (' + owner + ')' : ''));
    return true;
  }

  /* ---------------------------------------------------------------- hooks */

  // WinHttpConnect(hSession, pswzServerName, nServerPort, dwReserved)
  function winHttpConnect(owner) {
    return {
      onEnter: function (args) {
        this.host = readWide(args[1]);
        this.port = toUint(args[2]) & 0xffff;
      },
      onLeave: function (retval) {
        if (!this.host) return;
        storeConnection(handleKey(retval), {
          host: this.host,
          port: this.port,
          module: owner
        });
        emit('WinHttpConnect', {
          host: this.host,
          port: this.port || null,
          module: owner
        });
      }
    };
  }

  // WinHttpOpenRequest(hConnect, verb, objectName, version, referrer,
  //                    acceptTypes, flags) -- flags carry WINHTTP_FLAG_SECURE.
  function winHttpOpenRequest(owner) {
    return {
      onEnter: function (args) {
        var key = handleKey(args[0]);
        var conn = has(connections, key) ? connections[key] : null;
        var secure = (toUint(args[6]) & WINHTTP_FLAG_SECURE) !== 0;
        var scheme = secure ? 'https' : 'http';
        var host = conn ? conn.host : '';
        var port = (conn && conn.port) ? conn.port : defaultPort(scheme);
        var path = normalizePath(readWide(args[2]));
        this.info = {
          url: buildUrl(scheme, host, port, path),
          host: host,
          path: path,
          port: port,
          module: owner
        };
        emit('WinHttpOpenRequest', this.info);
      },
      onLeave: function (retval) {
        if (!this.info) return;
        storeRequest(handleKey(retval), this.info);
      }
    };
  }

  // Correlation only: proves the request handle actually went on the wire.
  function sendRequestHook(api, owner) {
    return {
      onEnter: function (args) {
        var key = handleKey(args[0]);
        if (!has(requests, key)) return;
        var info = requests[key];
        emit(api, {
          url: info.url,
          host: info.host,
          path: info.path,
          port: info.port,
          module: owner
        });
      }
    };
  }

  // InternetConnectW|A(hInternet, serverName, port, user, pass, service,
  //                    flags, context)
  function internetConnect(api, owner, wide) {
    return {
      onEnter: function (args) {
        this.host = wide ? readWide(args[1]) : readAnsi(args[1]);
        this.port = toUint(args[2]) & 0xffff;
      },
      onLeave: function (retval) {
        if (!this.host) return;
        storeConnection(handleKey(retval), {
          host: this.host,
          port: this.port,
          module: owner
        });
        emit(api, {host: this.host, port: this.port || null, module: owner});
      }
    };
  }

  // HttpOpenRequestW|A(hConnect, verb, objectName, version, referrer,
  //                    acceptTypes, flags, context)
  function httpOpenRequest(api, owner, wide) {
    return {
      onEnter: function (args) {
        var key = handleKey(args[0]);
        var conn = has(connections, key) ? connections[key] : null;
        var secure = (toUint(args[6]) & WINHTTP_FLAG_SECURE) !== 0;
        var scheme = secure ? 'https' : 'http';
        var host = conn ? conn.host : '';
        var port = (conn && conn.port) ? conn.port : defaultPort(scheme);
        var path = normalizePath(wide ? readWide(args[2]) : readAnsi(args[2]));
        this.info = {
          url: buildUrl(scheme, host, port, path),
          host: host,
          path: path,
          port: port,
          module: owner
        };
        emit(api, this.info);
      },
      onLeave: function (retval) {
        if (!this.info) return;
        storeRequest(handleKey(retval), this.info);
      }
    };
  }

  // InternetOpenUrlW|A(hInternet, url, headers, headersLength, flags, context)
  function internetOpenUrl(api, owner, wide) {
    return {
      onEnter: function (args) {
        var url = wide ? readWide(args[1]) : readAnsi(args[1]);
        if (!url) return;
        var parts = splitUrl(url);
        emit(api, {
          url: url,
          host: parts.host,
          path: parts.path,
          port: parts.port,
          module: owner
        });
      }
    };
  }

  // getaddrinfo / GetAddrInfoW / GetAddrInfoExW -- host-only weak signal for a
  // downloader whose HTTP client is statically linked but whose DNS is not.
  function resolverHook(api, owner, wide) {
    return {
      onEnter: function (args) {
        var host = wide ? readWide(args[0]) : readAnsi(args[0]);
        if (!host || host.length > 255) return;
        var service = wide ? readWide(args[1]) : readAnsi(args[1]);
        var port = /^\d{1,5}$/.test(service) ? parseInt(service, 10) : null;
        emit(api, {host: host, port: port, module: owner});
      }
    };
  }

  // curl_easy_setopt(handle, option, value) -- CURLOPT_URL takes a char*.
  function curlSetopt(owner) {
    return {
      onEnter: function (args) {
        if (toUint(args[1]) !== CURLOPT_URL) return;
        var url = readUtf8(args[2]);
        if (!url) return;
        var parts = splitUrl(url);
        emit('curl_easy_setopt', {
          url: url,
          host: parts.host,
          path: parts.path,
          port: parts.port,
          module: owner
        });
      }
    };
  }

  /* --------------------------------------------------------- install pass */

  var TARGETS = [
    {label: 'WinHttpConnect', module: 'winhttp.dll', symbol: 'WinHttpConnect',
      make: winHttpConnect},
    {label: 'WinHttpOpenRequest', module: 'winhttp.dll', symbol: 'WinHttpOpenRequest',
      make: winHttpOpenRequest},
    {label: 'WinHttpSendRequest', module: 'winhttp.dll', symbol: 'WinHttpSendRequest',
      make: function (owner) { return sendRequestHook('WinHttpSendRequest', owner); }},
    {label: 'InternetConnectW', module: 'wininet.dll', symbol: 'InternetConnectW',
      make: function (owner) { return internetConnect('InternetConnectW', owner, true); }},
    {label: 'InternetConnectA', module: 'wininet.dll', symbol: 'InternetConnectA',
      make: function (owner) { return internetConnect('InternetConnectA', owner, false); }},
    {label: 'HttpOpenRequestW', module: 'wininet.dll', symbol: 'HttpOpenRequestW',
      make: function (owner) { return httpOpenRequest('HttpOpenRequestW', owner, true); }},
    {label: 'HttpOpenRequestA', module: 'wininet.dll', symbol: 'HttpOpenRequestA',
      make: function (owner) { return httpOpenRequest('HttpOpenRequestA', owner, false); }},
    {label: 'HttpSendRequestW', module: 'wininet.dll', symbol: 'HttpSendRequestW',
      make: function (owner) { return sendRequestHook('HttpSendRequestW', owner); }},
    {label: 'HttpSendRequestA', module: 'wininet.dll', symbol: 'HttpSendRequestA',
      make: function (owner) { return sendRequestHook('HttpSendRequestA', owner); }},
    {label: 'InternetOpenUrlW', module: 'wininet.dll', symbol: 'InternetOpenUrlW',
      make: function (owner) { return internetOpenUrl('InternetOpenUrlW', owner, true); }},
    {label: 'InternetOpenUrlA', module: 'wininet.dll', symbol: 'InternetOpenUrlA',
      make: function (owner) { return internetOpenUrl('InternetOpenUrlA', owner, false); }},
    {label: 'getaddrinfo', module: 'ws2_32.dll', symbol: 'getaddrinfo',
      make: function (owner) { return resolverHook('getaddrinfo', owner, false); }},
    {label: 'GetAddrInfoW', module: 'ws2_32.dll', symbol: 'GetAddrInfoW',
      make: function (owner) { return resolverHook('GetAddrInfoW', owner, true); }},
    {label: 'GetAddrInfoExW', module: 'ws2_32.dll', symbol: 'GetAddrInfoExW',
      make: function (owner) { return resolverHook('GetAddrInfoExW', owner, true); }},
    // Whole-process export sweep: only worth doing every few attempts.
    {label: 'curl_easy_setopt', module: '*', symbol: 'curl_easy_setopt',
      slow: true, make: curlSetopt}
  ];

  function installAll() {
    var pending = 0;
    passModules = null;   // modules load lazily; re-enumerate once per pass
    for (var i = 0; i < TARGETS.length; i++) {
      var target = TARGETS[i];
      if (has(installed, target.label)) continue;
      if (target.slow && attempts > 0 && (attempts % SLOW_EVERY) !== 0) {
        pending++;
        continue;
      }
      try {
        if (!install(target)) pending++;
      } catch (e) {
        pending++;
      }
    }
    return pending;
  }

  function summary() {
    var labels = [];
    for (var label in installed) {
      if (has(installed, label) && installed[label] !== 'failed') labels.push(label);
    }
    labels.sort();
    return '[native_http_urls] ' + labels.length + '/' + TARGETS.length +
      ' hooks installed: ' + (labels.length ? labels.join(', ') : 'none');
  }

  try {
    var pendingNow = installAll();
    console.log(summary());
    if (pendingNow > 0) {
      var timer = setInterval(function () {
        attempts++;
        var before = installedCount;
        var pending = TARGETS.length;
        try {
          pending = installAll();
        } catch (e) {}
        if (installedCount !== before) console.log(summary());
        if (pending === 0) {
          clearInterval(timer);
          return;
        }
        if (!hinted && attempts >= HINT_AFTER && installedCount === 0) {
          hinted = true;
          console.log('[native_http_urls] no native HTTP stack loaded yet -- if ' +
            'nothing fires during the forced re-fetch the downloader links its ' +
            'TLS library statically; use mitmproxy as the fallback.');
        }
      }, 1000);
    }
  } catch (e) {
    console.log('[native_http_urls] install pass failed: ' + e);
  }
})();
