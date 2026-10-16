'use strict';
/* Capture title-screen resource requests before login; no account re-auth is needed. */
(
  function() {
    var buffers = {};
    var attached = {};
    var seenUrls = new Set();
    var knownResVers = new Set();

  function findRequestStart(buf) {
    var getStart = buf.indexOf('GET ');
    var postStart = buf.indexOf('POST ');
    if (getStart < 0) return postStart;
    if (postStart < 0) return getStart;
    return Math.min(getStart, postStart);
  }

  function pathHasResourceVersion(path) {
    var found = false;
    knownResVers.forEach(function(resVer) {
      if (path.indexOf(resVer) >= 0) found = true;
    });
    return found || /\d{8,}/.test(path);
  }

  function parseHttp(text) {
    try {
      var request = text.match(/^(GET|POST)\s+([^\s]+)\s+HTTP\/\d(?:\.\d)?/i);
      var hostMatch = text.match(/(?:^|\r\n)Host:\s*([^\r\n]+)/i);
      if (!request || !hostMatch) return;
      var method = request[1].toUpperCase();
      var path = request[2];
      var host = hostMatch[1].trim();
      if (!host || host.length > 1024 || !path || path.length > 65536) return;

      var resVer = text.match(/(?:^|\r\n)RES-VER:\s*(\d+)/i);
      if (resVer && resVer[1]) knownResVers.add(resVer[1]);
      var hostName = host.toLowerCase().replace(/:\d+$/, '');
      var lowerPath = path.toLowerCase();
      var looksResource = lowerPath.indexOf('manifest') >= 0 ||
          lowerPath.indexOf('master') >= 0 ||
          lowerPath.indexOf('.lz4') >= 0 ||
          pathHasResourceVersion(path);
      if (hostName === 'api.games.umamusume.com' && !looksResource) return;

      var url = 'https://' + host + path;
      if (seenUrls.has(url)) return;
      seenUrls.add(url);
      send({type: 'resource_req', method: method, host: host, path: path, url: url});
    } catch (e) {}
  }

  function parseChunk(key, chunk) {
    var buf = (buffers[key] || '') + chunk;
    if (buf.length > 2097152) buf = buf.substring(buf.length - 1048576);
    while (buf.length > 0) {
      var start = findRequestStart(buf);
      if (start < 0) {
        buffers[key] = buf.slice(-4096);
        return;
      }
      if (start > 0) buf = buf.substring(start);
      var headerEnd = buf.indexOf('\r\n\r\n');
      if (headerEnd < 0) {
        buffers[key] = buf;
        return;
      }
      var headers = buf.substring(0, headerEnd);
      var lm = headers.match(/Content-Length:\s*(\d+)/i);
      var length = lm ? parseInt(lm[1], 10) : 0;
      if (length > 2097152) {
        buffers[key] = '';
        return;
      }
      var total = headerEnd + 4 + length;
      if (length > 0 && buf.length < total) {
        buffers[key] = buf;
        return;
      }
      parseHttp(buf.substring(0, total));
      buf = buf.length > total ? buf.substring(total) : '';
    }
    buffers[key] = '';
  }

  function hookTls() {
    var ga = Process.findModuleByName('GameAssembly.dll');
    if (!ga) return false;
    var installFn = ga.findExportByName('il2cpp_unity_install_unitytls_interface');
    if (!installFn) return false;
    var rb = new Uint8Array(installFn.readByteArray(16));
    var realFn = installFn;
    if (rb[0] === 0xe9) {
      var off = rb[1] | (rb[2] << 8) | (rb[3] << 16) | (rb[4] << 24);
      if (off > 0x7fffffff) off -= 0x100000000;
      realFn = installFn.add(5 + off);
      rb = new Uint8Array(realFn.readByteArray(16));
    }
    var globalPtr = null;
    if (rb[0] === 0x48 && rb[1] === 0x89 && rb[2] === 0x0d) {
      var disp = rb[3] | (rb[4] << 8) | (rb[5] << 16) | (rb[6] << 24);
      if (disp > 0x7fffffff) disp -= 0x100000000;
      globalPtr = realFn.add(7 + disp);
    }
    if (!globalPtr) return false;
    var iface = globalPtr.readPointer();
    if (!iface || iface.isNull()) return false;
    var hookedTls = 0;
    [0xd0, 0xd8, 0xe0, 0xe8].forEach(function(off) {
      var addr = iface.add(off).readPointer();
      if (!addr || addr.isNull()) return;
      var key = 'tls_' + addr.toString();
      if (attached[key]) return;
      try {
          Interceptor.attach(addr, {
              onEnter: function(args) {
                  var len = args[2].toInt32();
                  if (len <= 0 || len > 1048576 || args[1].isNull()) return;
                  try {
                      var bytes = args[1].readByteArray(len);
                      var u8 = new Uint8Array(bytes);
                      var s = '';
                      for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
                      parseChunk(args[0].toString(), s);
                  } catch (e) {}
              }
          });
          attached[key] = true;
          hookedTls++;
      } catch (e) {}
    });
    return hookedTls > 0;
  }

  var tlsDone = false;
  var timer = setInterval(function() {
    try {
        if (!tlsDone) tlsDone = hookTls();
        if (tlsDone) clearInterval(timer);
    } catch (e) {}
  }, 1000);
})();
