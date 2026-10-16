'use strict';

// Shared preamble for hooks that call IL2CPP APIs from Frida's JS thread.
var Il2CppThreadGuard = (function () {
    var liveTokens = [];

    function isNullPointer(value) {
        if (value === null || value === undefined) return true;
        try {
            return typeof value.isNull === 'function' && value.isNull();
        } catch (e) {
            return true;
        }
    }

    function attach(gameAssembly, domainGetName, threadAttachName, threadDetachName, emitLog) {
        function log(message) {
            try {
                emitLog(message);
                return;
            } catch (e) {}
            try { console.log('[il2cpp-thread-guard] ' + message); } catch (e2) {}
        }

        function findExport(name, required) {
            var address = null;
            try { address = gameAssembly.findExportByName(name); } catch (e) {
                log((required ? 'GC-safe hook aborted: ' : '') +
                    'could not resolve GameAssembly.dll export ' + name + ': ' + e);
                return null;
            }
            if (isNullPointer(address)) {
                if (required) {
                    log('GC-safe hook aborted: required GameAssembly.dll export ' +
                        name + ' was not found; no unmanaged Frida thread will call IL2CPP.');
                }
                return null;
            }
            return address;
        }

        var domainGetAddress = findExport(domainGetName, true);
        var threadAttachAddress = findExport(threadAttachName, true);
        var threadDetachAddress = findExport(threadDetachName, true);
        if (!domainGetAddress || !threadAttachAddress || !threadDetachAddress) return null;

        var domainGet;
        var threadAttach;
        var threadDetach;
        try {
            domainGet = new NativeFunction(domainGetAddress, 'pointer', []);
            threadAttach = new NativeFunction(threadAttachAddress, 'pointer', ['pointer']);
            threadDetach = new NativeFunction(threadDetachAddress, 'void', ['pointer']);
        } catch (e) {
            log('GC-safe hook aborted: could not create IL2CPP thread functions: ' + e);
            return null;
        }

        var domain;
        var attachedThread;
        try {
            // il2cpp_domain_get is the one permitted call before registration; attach
            // immediately afterward, before any metadata lookup or managed access.
            domain = domainGet();
            if (isNullPointer(domain)) {
                log('GC-safe hook aborted: il2cpp_domain_get returned null.');
                return null;
            }
            attachedThread = threadAttach(domain);
            if (isNullPointer(attachedThread)) {
                log('GC-safe hook aborted: il2cpp_thread_attach returned null.');
                return null;
            }
        } catch (e) {
            log('GC-safe hook aborted while attaching the Frida JS thread: ' + e);
            return null;
        }

        // A mod loader such as hachimi can change thread/GC timing, exposing an
        // unregistered Frida thread that happened to survive under earlier timing.
        var state = {
            active: true,
            moduleName: gameAssembly.name,
            thread: attachedThread,
            detachFunction: threadDetach
        };

        function detachNow() {
            if (!state.active) return;
            state.active = false;
            try {
                if (!Process.findModuleByName(state.moduleName)) return;
                state.detachFunction(state.thread);
            } catch (e) {
                // Unload can race process/runtime teardown; detachment is best-effort.
                log('Ignoring IL2CPP thread detach failure during script unload: ' + e);
            }
        }

        var keepAlive = {};
        try {
            Script.bindWeak(keepAlive, detachNow);
            liveTokens.push(keepAlive);
        } catch (e) {
            log('GC-safe hook aborted: could not register script-unload detach: ' + e);
            detachNow();
            return null;
        }

        log('Attached Frida JS thread to the IL2CPP runtime.');
        return {
            domain: domain,
            keepAlive: keepAlive,
            detach: detachNow,
            nativeFunction: function (name, returnType, argumentTypes, required) {
                var address = findExport(name, required !== false);
                if (!address) return null;
                try {
                    return new NativeFunction(address, returnType, argumentTypes);
                } catch (e) {
                    log('Could not create NativeFunction for ' + name + ': ' + e);
                    return null;
                }
            }
        };
    }

    return {attach: attach};
}());
