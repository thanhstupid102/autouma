const SteamUser = require("steam-user");

const STEAM_CLIENT_PROFILE = Object.freeze({
  clientOS: SteamUser.EOSType.Win11,
});

const args = process.argv.slice(2);
let username = "";
let password = "";
let appid = 3224770;
let code = "";
let refreshToken = "";
let dataDirectory = null;
let machineName = "";

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--username") username = args[++i];
  else if (args[i] === "--password") password = args[++i];
  else if (args[i] === "--appid") appid = parseInt(args[++i]);
  else if (args[i] === "--code") code = args[++i];
  else if (args[i] === "--refresh-token") refreshToken = args[++i];
  else if (args[i] === "--data-directory") dataDirectory = args[++i];
  else if (args[i] === "--machine-name") machineName = args[++i];
}

if (!refreshToken && (!username || !password)) {
  process.stderr.write(
    "Usage: ticket_gen --refresh-token T | --username X --password Y " +
    "[--code Z] [--data-directory PATH] [--machine-name NAME]\\n"
  );
  process.exit(1);
}

// The Python wrapper supplies a private state-root directory. Null disables the
// library's OS-specific app-data persistence for direct standalone invocation.
const client = new SteamUser({ dataDirectory: dataDirectory });
let capturedRefreshToken = "";

const loginOpts = refreshToken
  ? { refreshToken: refreshToken }
  : { accountName: username, password: password };

if (!refreshToken && code) {
  loginOpts.twoFactorCode = code;
}
Object.assign(loginOpts, STEAM_CLIENT_PROFILE);
if (machineName) {
  loginOpts.machineName = machineName;
}

client.logOn(loginOpts);

client.on("refreshToken", (token) => {
  capturedRefreshToken = token;
});

client.on("steamGuard", (domain, callback) => {
  process.stderr.write("NEED_GUARD:" + (domain || "2fa") + "\\n");
  process.exit(2);
});

client.on("error", (err) => {
  if (refreshToken) {
    process.stderr.write("TOKEN_INVALID:" + err.message + "\\n");
    process.exit(4);
  }
  process.stderr.write("ERROR:" + err.message + "\\n");
  process.exit(1);
});

client.on("loggedOn", () => {
  process.stderr.write(
    "Logged in as " + client.steamID.getSteamID64() + "\\n"
  );
  client.createAuthSessionTicket(appid, (err, sessionTicket) => {
    if (err) {
      process.stderr.write("Ticket error: " + err.message + "\\n");
      process.exit(1);
    }
    const buf = Buffer.isBuffer(sessionTicket) ? sessionTicket : sessionTicket.sessionTicket || sessionTicket;
    const result = {
      steam_id: client.steamID.getSteamID64(),
      session_ticket: Buffer.from(buf).toString("hex").toUpperCase(),
    };
    if (capturedRefreshToken) {
      result.refresh_token = capturedRefreshToken;
    }
    process.stdout.write(JSON.stringify(result) + "\\n");
    process.stderr.write(
      "Ticket generated (" + Buffer.from(buf).length + " bytes)\\n"
    );
    setTimeout(() => process.exit(0), 500);
  });
});
