'use strict';
// Full request+response traffic hook.
//
// Unlike integrations/frida/js/uma_network.js (which taps the TLS WRITE buffer and only
// sees encrypted REQUEST bodies), this hooks the game's own IL2CPP HTTP helper
// methods, which operate on PLAINTEXT msgpack BEFORE encryption / AFTER
// decryption -- so we get BOTH directions with no AES key needed:
//   Gallop.HttpHelper.CompressRequest(byte[])   onEnter  -> request msgpack
//   Gallop.HttpHelper.DecompressResponse(byte[]) onLeave  -> response msgpack
//   Cute.Http.WWWRequest.Post(url, body, headers) onEnter -> the request URL
//
// These are resolved via the il2cpp_* runtime exports (il2cpp_class_from_name,
// il2cpp_class_get_method_from_name), which are NOT obfuscated even though the
// binary is VM-packed -- the packing hides method BODIES from static tools, but
// the runtime metadata API still resolves and hooks them fine.
//
// Emits Frida messages: send({t:'Q', path:<url|null>}, <bytes>) for requests,
// send({t:'R'}, <bytes>) for responses, send({t:'log', msg}) for diagnostics.
// Ported from the Icarus recorder's proven hook.
(function () {
    function log(message) {
        send({t: 'log', msg: message});
    }

    var ga = Process.findModuleByName('GameAssembly.dll');
    if (!ga) {
        log('GC-safe hook aborted: GameAssembly.dll is not loaded.');
        return;
    }

    var il2cppThread = Il2CppThreadGuard.attach(
        ga,
        'il2cpp_domain_get',
        'il2cpp_thread_attach',
        'il2cpp_thread_detach',
        log
    );
    if (!il2cppThread) return;

    var il2cpp_domain_get_assemblies = il2cppThread.nativeFunction(
        'il2cpp_domain_get_assemblies', 'pointer', ['pointer', 'pointer']);
    var il2cpp_assembly_get_image = il2cppThread.nativeFunction(
        'il2cpp_assembly_get_image', 'pointer', ['pointer']);
    var il2cpp_class_from_name = il2cppThread.nativeFunction(
        'il2cpp_class_from_name', 'pointer', ['pointer', 'pointer', 'pointer']);
    var il2cpp_class_get_method_from_name = il2cppThread.nativeFunction(
        'il2cpp_class_get_method_from_name', 'pointer', ['pointer', 'pointer', 'int']);
    var il2cpp_array_length_fn = il2cppThread.nativeFunction(
        'il2cpp_array_length', 'uint', ['pointer']);
    if (!il2cpp_domain_get_assemblies || !il2cpp_assembly_get_image ||
            !il2cpp_class_from_name || !il2cpp_class_get_method_from_name ||
            !il2cpp_array_length_fn) {
        il2cppThread.detach();
        return;
    }

    var il2cpp_array_addr = il2cppThread.nativeFunction(
        'il2cpp_array_addr_with_size', 'pointer', ['pointer', 'int', 'uint'], false);

    var domain = il2cppThread.domain;
    var sizeOut = Memory.alloc(4);
    var assemblies = il2cpp_domain_get_assemblies(domain, sizeOut);
    var assemblyCount = sizeOut.readU32();

    function findClass(ns, cn) {
        var nsPtr = Memory.allocUtf8String(ns);
        var cnPtr = Memory.allocUtf8String(cn);
        for (var i = 0; i < assemblyCount; i++) {
            var image = il2cpp_assembly_get_image(assemblies.add(i * Process.pointerSize).readPointer());
            var klass = il2cpp_class_from_name(image, nsPtr, cnPtr);
            if (!klass.isNull()) return klass;
        }
        return null;
    }

    var foundClass = findClass('Gallop', 'HttpHelper');

    if (foundClass) {
        function readManagedArray(arr) {
            var len = il2cpp_array_length_fn(arr);
            if (len <= 0 || len > 50 * 1024 * 1024) return null;
            var dataPtr = il2cpp_array_addr ? il2cpp_array_addr(arr, 1, 0) : arr.add(0x20);
            return dataPtr.readByteArray(len);
        }

        // ---- request URL capture via Cute.Http.WWWRequest.Post ----------------
        // HttpHelper only compresses; the real send is WWWRequest.Post(url, body,
        // headers), fired right AFTER CompressRequest on the same thread. Hold the
        // plaintext body from CompressRequest and emit it once Post gives the URL.
        // If Post can't be hooked, usePending stays false and bodies are sent
        // immediately without a path (body capture never regresses).
        var pendingBody = {};
        var usePending = false;
        function readCsString(p) {
            if (p.isNull()) return null;
            var len = p.add(0x10).readS32();
            if (len <= 0 || len > 4096) return null;
            return p.add(0x14).readUtf16String(len);
        }
        try {
            var wwwClass = findClass('Cute.Http', 'WWWRequest');
            if (wwwClass) {
                var postName = Memory.allocUtf8String('Post');
                var postM = il2cpp_class_get_method_from_name(wwwClass, postName, 3);
                if (!postM.isNull()) {
                    Interceptor.attach(postM.readPointer(), {
                        onEnter: function(args) {
                            try {
                                var url = readCsString(args[1]);  // args[0]=this, args[1]=url
                                var tid = this.threadId;
                                var body = pendingBody[tid];
                                delete pendingBody[tid];
                                if (body) send({t: 'Q', path: url || null}, body);
                            } catch (e) {}
                        }
                    });
                    usePending = true;
                    send({t: 'log', msg: 'path-capture: hooked WWWRequest.Post(url, body, headers)'});
                }
            }
            if (!usePending) send({t: 'log', msg: 'path-capture: WWWRequest.Post not found; paths off, capture normal'});
        } catch (e) {
            send({t: 'log', msg: 'path-capture error: ' + e});
        }

        var decompName = Memory.allocUtf8String('DecompressResponse');
        var decompMethod = il2cpp_class_get_method_from_name(foundClass, decompName, 1);
        if (!decompMethod.isNull()) {
            Interceptor.attach(decompMethod.readPointer(), {
                onLeave: function(retval) {
                    if (!retval.isNull()) {
                        try {
                            var data = readManagedArray(retval);
                            if (data) send({t: 'R'}, data);
                        } catch (e) {}
                    }
                }
            });
            send({t: 'log', msg: 'hooked HttpHelper.DecompressResponse'});
        } else {
            send({t: 'log', msg: 'DecompressResponse not found -- responses will not be captured'});
        }

        var compName = Memory.allocUtf8String('CompressRequest');
        var compMethod = il2cpp_class_get_method_from_name(foundClass, compName, 1);
        if (!compMethod.isNull()) {
            Interceptor.attach(compMethod.readPointer(), {
                onEnter: function(args) {
                    var data = null;
                    try { data = readManagedArray(args[0]); } catch (e) {}
                    if (!data) { try { data = readManagedArray(args[1]); } catch (e2) {} }
                    if (!data) return;
                    if (usePending) {
                        var tid = this.threadId;
                        if (pendingBody[tid]) { try { send({t: 'Q', path: null}, pendingBody[tid]); } catch (e3) {} }
                        pendingBody[tid] = data;
                    } else {
                        send({t: 'Q', path: null}, data);
                    }
                }
            });
            send({t: 'log', msg: 'hooked HttpHelper.CompressRequest'});
        } else {
            send({t: 'log', msg: 'CompressRequest not found -- requests will not be captured'});
        }
    } else {
        send({t: 'log', msg: 'Gallop.HttpHelper class not found'});
    }
}());
