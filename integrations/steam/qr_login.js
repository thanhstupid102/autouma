// Standalone Steam QR login. Emits one JSON object per line on stdout:
//   {"type":"challenge","url":"<steam qr challenge url>"}
//   {"type":"authenticated","refresh_token":"<jwt>","steam_id":"<id64>"}
// On failure emits {"type":"error","message":"..."} and exits non-zero.
// stderr is human log only; stdout is the machine channel.
const { LoginSession, EAuthTokenPlatformType } = require("steam-session");

const STEAM_CLIENT_PROFILE = Object.freeze({
  platformType: EAuthTokenPlatformType.SteamClient,
});

const args = process.argv.slice(2);
let machineFriendlyName = "";
for (let i = 0; i < args.length; i++) {
  if (args[i] === "--machine-name") machineFriendlyName = args[++i];
}

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

async function main() {
  const options = machineFriendlyName ? {machineFriendlyName} : {};
  const session = new LoginSession(
    STEAM_CLIENT_PROFILE.platformType,
    options,
  );

  session.on("error", (err) => {
    emit({ type: "error", message: String(err && err.message || err) });
    process.exit(1);
  });

  session.on("timeout", () => {
    emit({ type: "error", message: "QR login timed out" });
    process.exit(3);
  });

  session.on("authenticated", () => {
    emit({
      type: "authenticated",
      refresh_token: session.refreshToken,
      steam_id: session.steamID ? session.steamID.getSteamID64() : "",
    });
    process.stderr.write("QR authenticated\n");
    setTimeout(() => process.exit(0), 200);
  });

  const startResult = await session.startWithQR();
  emit({ type: "challenge", url: startResult.qrChallengeUrl });
  process.stderr.write("QR challenge emitted; waiting for scan\n");
}

main().catch((err) => {
  emit({ type: "error", message: String(err && err.message || err) });
  process.exit(1);
});
