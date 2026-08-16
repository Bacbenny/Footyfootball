import { mkdir, writeFile } from "node:fs/promises";

const SOURCES = {
  watchFooty: "https://api.watchfooty.st",
  cdnLive:
    "https://api.cdnlivetv.tv/api/v1/events/sports/?user=cdnlivetv&plan=free",
  streamedMatches: "https://streamed.pk/api/matches/football",
  streamedStream: "https://streamed.pk/api/stream",
};

const OUTPUT_DIR = new URL("../output/", import.meta.url);
const TIMEOUT_MS = 6_000;
const STREAM_CHECK_TIMEOUT_MS = 5_000;
const BROWSER_TIMEOUT_MS = 15_000;
const BROWSER_WAIT_MS = 6_000;
const VIETNAM_TIME_ZONE = "Asia/Ho_Chi_Minh";
const PLAYLIST_GROUP = "FoottyLive";
const QUALITY_SCORE = {
  FHD: 400,
  "1080P": 400,
  UHD: 450,
  "4K": 450,
  HD: 300,
  "720P": 300,
  SD: 100,
};
const PROVIDER_SCORE = {
  watchfooty: 30,
  cdnlive: 20,
  streamed: 10,
};

let browserInstance = null;
let playwrightModulePromise = null;

function text(value) {
  return typeof value === "string" ? value.trim() : "";
}

function validUrl(value) {
  try {
    const url = new URL(text(value));
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}

function absoluteAssetUrl(value) {
  const asset = text(value);
  if (!asset) return "";
  if (validUrl(asset)) return asset;
  return `${SOURCES.watchFooty}${asset.startsWith("/") ? asset : `/${asset}`}`;
}

function slug(value) {
  return text(value)
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function words(value) {
  return new Set(slug(value).split(/\s+/).filter((word) => word.length > 2));
}

function teamsMatch(left, right) {
  const a = words(left);
  const b = words(right);
  if (!a.size || !b.size) return false;
  const shared = [...a].filter((word) => b.has(word)).length;
  return shared >= 2 || shared / Math.min(a.size, b.size) >= 0.6;
}

function extractTeams(match) {
  const home = text(match?.teams?.home?.name);
  const away = text(match?.teams?.away?.name);
  if (home && away) return { home, away };

  const title = text(match?.title);
  const parts = title.split(/\s+vs\.?\s+|\s+v\.?\s+/i);
  return {
    home: text(parts[0]) || "Home",
    away: text(parts[1]) || "Away",
  };
}

async function fetchJson(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      headers: {
        Accept: "application/json",
        "User-Agent": "Footyfootball-playlist/1.0",
      },
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

async function safeFetch(url, fallback) {
  try {
    return await fetchJson(url);
  } catch (error) {
    console.warn(`Source unavailable: ${url} (${error.message})`);
    return fallback;
  }
}

function isDirectMediaUrl(url) {
  return /\.(m3u8|mpd|mp4|ts)(?:$|[?#])/i.test(text(url));
}

function extractDirectMediaUrl(html, pageUrl) {
  const normalized = text(html)
    .replace(/\\u0026/gi, "&")
    .replace(/\\\//g, "/")
    .replace(/&amp;/gi, "&");
  const matches = normalized.match(
    /(?:https?:)?\/\/[^"'\\\s<>]+?\.(?:m3u8|mpd|mp4|ts)(?:\?[^"'\\\s<>]*)?/gi,
  ) || [];

  for (const match of matches) {
    const candidate = match.startsWith("//") ? `https:${match}` : match;
    if (validUrl(candidate)) return candidate;
  }

  const relative = normalized.match(
    /["'(](\/[^"'()\s<>]+?\.(?:m3u8|mpd|mp4|ts)(?:\?[^"'()\s<>]*)?)/i,
  );
  if (relative) {
    try {
      return new URL(relative[1], pageUrl).toString();
    } catch {
      return null;
    }
  }
  return null;
}

async function resolvePlayableCandidate(candidate) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), STREAM_CHECK_TIMEOUT_MS);
  try {
    const response = await fetch(candidate.url, {
      headers: {
        Accept: "*/*",
        Range: "bytes=0-4095",
        "User-Agent": "Footyfootball-playlist/1.0",
      },
      redirect: "follow",
      signal: controller.signal,
    });
    if (!response.ok) return null;

    const contentType = (response.headers.get("content-type") || "").toLowerCase();
    const isManifest =
      /\.m3u8(?:$|\?)/i.test(candidate.url) ||
      contentType.includes("mpegurl") ||
      contentType.includes("vnd.apple.mpegurl");
    if (isManifest) {
      const body = await response.text();
      return body.includes("#EXTM3U")
        ? { ...candidate, streamCheck: "verified", resolution: "direct" }
        : null;
    }

    if (
      contentType.startsWith("video/") ||
      contentType.startsWith("audio/") ||
      contentType.includes("dash+xml") ||
      contentType.includes("octet-stream") ||
      isDirectMediaUrl(candidate.url)
    ) {
      return { ...candidate, streamCheck: "verified", resolution: "direct" };
    }

    if (!contentType.includes("text/html") && !contentType.includes("text/plain")) {
      return null;
    }

    const directUrl = extractDirectMediaUrl(await response.text(), candidate.url);
    if (directUrl && directUrl !== candidate.url) {
      return resolvePlayableCandidate({
        ...candidate,
        url: directUrl,
        resolution: "resolved",
      });
    }

    if (candidate.allowBrowser) {
      const browserUrl = await resolveEmbedWithBrowser(candidate.url);
      if (browserUrl) {
        return resolvePlayableCandidate({
          ...candidate,
          url: browserUrl,
          allowBrowser: false,
          resolution: "browser",
        });
      }
    }
    return null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

async function resolveEmbedWithBrowser(url) {
  try {
    playwrightModulePromise ||= import("playwright");
    const { chromium } = await playwrightModulePromise;
    browserInstance ||= await chromium.launch({
      headless: true,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });
    const page = await browserInstance.newPage({
      userAgent: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
      viewport: { width: 1280, height: 720 },
    });
    const mediaUrls = new Set();
    const remember = (candidateUrl) => {
      if (
        isDirectMediaUrl(candidateUrl) &&
        !/(analytics|beacon|pixel|doubleclick|ads?[-_])/i.test(candidateUrl)
      ) {
        mediaUrls.add(candidateUrl);
      }
    };
    page.on("request", (request) => remember(request.url()));
    page.on("response", async (response) => {
      remember(response.url());
      try {
        const contentType = (await response.headerValue("content-type")) || "";
        if (
          contentType.includes("mpegurl") ||
          contentType.includes("dash+xml")
        ) {
          remember(response.url());
        }
      } catch {}
    });

    await page.goto(url, {
      waitUntil: "domcontentloaded",
      timeout: BROWSER_TIMEOUT_MS,
    });
    await page.locator("video").first().click({ force: true, timeout: 1_000 }).catch(() => {});
    await page.waitForTimeout(BROWSER_WAIT_MS);
    await page.close();
    return [...mediaUrls][0] || null;
  } catch {
    return null;
  }
}

async function mapWithConcurrency(items, limit, mapper) {
  const results = [];
  let nextIndex = 0;
  const workerCount = Math.min(limit, items.length);

  async function worker() {
    while (nextIndex < items.length) {
      const index = nextIndex++;
      results[index] = await mapper(items[index], index);
    }
  }

  await Promise.all(Array.from({ length: workerCount }, () => worker()));
  return results;
}

function quality(value) {
  return text(value).toUpperCase().replace(/\s/g, "");
}

function addCandidate(candidates, candidate) {
  const url = text(candidate.url);
  if (!validUrl(url)) return;

  const normalized = {
    url,
    provider: text(candidate.provider) || "unknown",
    quality: quality(candidate.quality) || "SD",
    label: text(candidate.label),
  };
  const score =
    (QUALITY_SCORE[normalized.quality] ?? 0) +
    (PROVIDER_SCORE[normalized.provider] ?? 0) +
    (/\.m3u8(?:$|\?)/i.test(url) ? 8 : 0) +
    (/\.mp4(?:$|\?)/i.test(url) ? 4 : 0);
  const existing = candidates.find((item) => item.url === url);
  if (!existing || score > existing.score) {
    const next = { ...normalized, score };
    if (existing) candidates[candidates.indexOf(existing)] = next;
    else candidates.push(next);
  }
}

const MATCH_EXPIRY_MS = 3 * 60 * 60 * 1000;

function statusFor(match) {
  const timestamp = Number(match?.timestamp || 0);
  const now = Date.now();
  const explicit = ["in", "live"].includes(text(match?.status).toLowerCase());
  const withinLiveWindow =
    timestamp > 0 && now >= timestamp && now - timestamp < 125 * 60 * 1000;
  return explicit || withinLiveWindow ? "live" : "upcoming";
}

function isMatchActive(match) {
  const timestamp = Number(match?.timestamp || 0);
  if (!timestamp) return true;
  const now = Date.now();
  return now - timestamp < MATCH_EXPIRY_MS;
}

function normalizeMatch(raw) {
  const { home, away } = extractTeams(raw);
  return {
    id: text(raw?.matchId || raw?.id),
    title: text(raw?.title) || `${home} vs ${away}`,
    home,
    away,
    league: text(raw?.league || raw?.tournament) || "Football",
    timestamp: Number(raw?.timestamp || raw?.date || 0),
    status: statusFor(raw),
    homeLogo: absoluteAssetUrl(raw?.teams?.home?.logoUrl),
    awayLogo: absoluteAssetUrl(raw?.teams?.away?.logoUrl),
    streams: Array.isArray(raw?.streams) ? raw.streams : [],
  };
}

async function getWatchFootyMatches() {
  const data = await safeFetch(
    `${SOURCES.watchFooty}/api/v1/matches/football`,
    [],
  );
  return Array.isArray(data) ? data.map(normalizeMatch) : [];
}

async function addWatchFootyCandidates(match, candidates) {
  for (const stream of match.streams) {
    addCandidate(candidates, {
      url: stream.url,
      quality: stream.quality,
      label: stream.source,
      provider: "watchfooty",
    });
  }

  if (candidates.length || !match.id) return;
  const detail = await safeFetch(
    `${SOURCES.watchFooty}/api/v1/match/${encodeURIComponent(match.id)}`,
    null,
  );
  const raw = Array.isArray(detail) ? detail[0] : detail;
  for (const stream of raw?.streams || []) {
    addCandidate(candidates, {
      url: stream.url,
      quality: stream.quality,
      label: stream.source,
      provider: "watchfooty",
    });
  }
}

async function addCdnLiveCandidates(match, candidates, cdnData) {
  const events = cdnData?.["cdn-live-tv"] || {};
  const soccer = events.Soccer || events.Football || [];
  for (const event of Array.isArray(soccer) ? soccer : []) {
    const eventTitle = `${text(event.homeTeam)} vs ${text(event.awayTeam)}`;
    if (!teamsMatch(match.title, eventTitle)) continue;
    for (const channel of event.channels || []) {
      addCandidate(candidates, {
        url: channel.url,
        quality: "HD",
        label: channel.channel_name,
        provider: "cdnlive",
      });
    }
  }
}

async function addStreamedCandidates(match, candidates, streamedMatches) {
  const requests = [];
  for (const streamed of Array.isArray(streamedMatches) ? streamedMatches : []) {
    if (!teamsMatch(match.title, streamed.title)) continue;
    for (const source of streamed.sources || []) {
      requests.push({ source });
    }
  }

  await mapWithConcurrency(requests, 8, async ({ source }) => {
    const data = await safeFetch(
        `${SOURCES.streamedStream}/${encodeURIComponent(source.source)}/${encodeURIComponent(source.id)}`,
        null,
      );
    const values = Array.isArray(data) ? data : [data];
    for (const value of values) {
      addCandidate(candidates, {
        url: value?.embedUrl || value?.url || value?.streamUrl || value?.iframe,
        quality: value?.hd ? "HD" : "SD",
        provider: "streamed",
        label: source.source,
      });
    }
  });
}

async function addStreamedOnlyMatches(streamedMatches, existingIds) {
  const extra = [];
  for (const streamed of Array.isArray(streamedMatches) ? streamedMatches : []) {
    const fakeId = `sm-${streamed.id || slug(streamed.title)}`;
    if (existingIds.has(fakeId)) continue;
    existingIds.add(fakeId);

    const requests = (streamed.sources || []).map((source) => ({ source }));
    const candidates = [];
    await mapWithConcurrency(requests, 8, async ({ source }) => {
      const data = await safeFetch(
        `${SOURCES.streamedStream}/${encodeURIComponent(source.source)}/${encodeURIComponent(source.id)}`,
        null,
      );
      const values = Array.isArray(data) ? data : [data];
      for (const value of values) {
        addCandidate(candidates, {
          url: value?.embedUrl || value?.url || value?.streamUrl || value?.iframe,
          quality: value?.hd ? "HD" : "SD",
          provider: "streamed",
          label: source.source,
        });
      }
    });
    if (candidates.length) {
      const home = text(streamed?.teams?.home?.name);
      const away = text(streamed?.teams?.away?.name);
      const homeLogo = streamed?.teams?.home?.badge
        ? `https://streamed.pk/api/team/badge/${streamed.teams.home.badge}`
        : "";
      const awayLogo = streamed?.teams?.away?.badge
        ? `https://streamed.pk/api/team/badge/${streamed.teams.away.badge}`
        : "";
      extra.push({
        id: fakeId,
        title: streamed.title,
        home: home || text(streamed.title.split(/\s+vs\.?\s+/i)[0]),
        away: away || text(streamed.title.split(/\s+vs\.?\s+/i)[1]),
        league: text(streamed.league) || "Football",
        timestamp: Number(streamed.date || streamed.timestamp || 0),
        status: statusFor({ timestamp: streamed.date || streamed.timestamp, status: "upcoming" }),
        homeLogo,
        awayLogo,
        streams: [],
        _candidates: candidates,
      });
    }
  }
  return extra;
}

async function addCdnOnlyMatches(cdnData, existingIds) {
  const events = cdnData?.["cdn-live-tv"] || {};
  const soccer = events.Soccer || events.Football || [];
  const extra = [];
  for (const event of Array.isArray(soccer) ? soccer : []) {
    const home = text(event.homeTeam);
    const away = text(event.awayTeam);
    const fakeId = `cdn-${event.gameID || slug(home) + "-" + slug(away)}`;
    if (existingIds.has(fakeId)) continue;
    existingIds.add(fakeId);

    const candidates = [];
    for (const channel of event.channels || []) {
      addCandidate(candidates, {
        url: channel.url,
        quality: "HD",
        label: channel.channel_name,
        provider: "cdnlive",
      });
    }
    if (candidates.length) {
      const ts = event.start ? new Date(event.start + " UTC").getTime() : 0;
      extra.push({
        id: fakeId,
        title: `${home} vs ${away}`,
        home,
        away,
        league: text(event.tournament) || "Football",
        timestamp: ts,
        status: statusFor({ timestamp: ts, status: event.status }),
        homeLogo: text(event.homeTeamIMG),
        awayLogo: text(event.awayTeamIMG),
        streams: [],
        _candidates: candidates,
      });
    }
  }
  return extra;
}

function escapeAttribute(value) {
  return text(value).replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}

function playlistTitle(match) {
  const timestamp = match.timestamp
    ? new Intl.DateTimeFormat("vi-VN", {
        timeZone: VIETNAM_TIME_ZONE,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        day: "2-digit",
        month: "2-digit",
        hourCycle: "h23",
      })
        .formatToParts(new Date(match.timestamp))
        .reduce((parts, part) => {
          parts[part.type] = part.value;
          return parts;
        }, {})
    : { hour: "--", minute: "--", second: "--", day: "--", month: "--" };

  return `${timestamp.hour}:${timestamp.minute}:${timestamp.second} - ${timestamp.day}/${timestamp.month} | ${match.home} VS ${match.away} | ${match.league}`;
}

function toExtInf(match, candidate) {
  const title = playlistTitle(match);
  const attrs = [
    `tvg-id="footy-${escapeAttribute(match.id)}"`,
    `tvg-name="${escapeAttribute(title)}"`,
    `group-title="${PLAYLIST_GROUP}"`,
  ];
  if (match.homeLogo) attrs.push(`tvg-logo="${escapeAttribute(match.homeLogo)}"`);
  return `#EXTINF:-1 ${attrs.join(" ")},${title}`;
}

async function chooseBestStream(match, candidates) {
  if (!candidates.length) return null;
  candidates.sort((a, b) => b.score - a.score);

  if (match.status === "upcoming") {
    return { ...candidates[0], streamCheck: "pending", resolution: "embed" };
  }

  const playable = (
    await mapWithConcurrency(candidates, 3, (candidate) =>
      resolvePlayableCandidate({
        ...candidate,
        allowBrowser: true,
      }),
    )
  ).filter(Boolean);

  if (playable.length) {
    playable.sort((a, b) => b.score - a.score);
    return playable[0];
  }

  console.warn(`Using embed fallback for live match: ${match.title}`);
  return { ...candidates[0], streamCheck: "pending", resolution: "embed" };
}

async function main() {
  const matches = await getWatchFootyMatches();
  const cdnData = await safeFetch(SOURCES.cdnLive, {});
  const streamedMatches = await safeFetch(SOURCES.streamedMatches, []);
  const entries = [];
  const unavailable = [];
  const seenMatchIds = new Set();
  const uniqueMatches = [];

  for (const match of matches) {
    if (!match.id || seenMatchIds.has(match.id)) continue;
    seenMatchIds.add(match.id);
    uniqueMatches.push(match);
  }

  const streamedOnly = await addStreamedOnlyMatches(streamedMatches, seenMatchIds);
  const cdnOnly = await addCdnOnlyMatches(cdnData, seenMatchIds);
  const allMatches = [...uniqueMatches, ...streamedOnly, ...cdnOnly].filter(isMatchActive);

  const resolvedEntries = await mapWithConcurrency(allMatches, 12, async (match) => {
    const candidates = match._candidates ? match._candidates.slice() : [];
    if (!match._candidates) {
      await addWatchFootyCandidates(match, candidates);
      await addCdnLiveCandidates(match, candidates, cdnData);
      await addStreamedCandidates(match, candidates, streamedMatches);
    }

    const best = await chooseBestStream(match, candidates);
    if (!best) {
      unavailable.push({
        id: match.id,
        title: playlistTitle(match),
        status: match.status,
        league: match.league,
        candidateCount: candidates.length,
        providers: [...new Set(candidates.map((candidate) => candidate.provider))],
        reason: candidates.length
          ? "no_direct_playable_media_url"
          : "no_upstream_stream_candidate",
      });
      return null;
    }
    return best ? { match, stream: best } : null;
  });
  entries.push(...resolvedEntries.filter(Boolean));

  entries.sort((a, b) => {
    const liveOrder = Number(b.match.status === "live") - Number(a.match.status === "live");
    if (liveOrder) return liveOrder;
    return (a.match.timestamp || 0) - (b.match.timestamp || 0);
  });

  const lines = [
    "#EXTM3U",
    "# Generated by Footyfootball",
    "# Each fixture intentionally contains one highest-ranked stream only.",
  ];
  for (const { match, stream } of entries) {
    lines.push(toExtInf(match, stream), stream.url);
  }

  await mkdir(OUTPUT_DIR, { recursive: true });
  await writeFile(new URL("footyfootball.m3u", OUTPUT_DIR), `${lines.join("\n")}\n`);
  await writeFile(
    new URL("footyfootball.json", OUTPUT_DIR),
    `${JSON.stringify(
      {
        source: "OgBek/footyLive-compatible public provider APIs",
        count: entries.length,
        matches: entries.map(({ match, stream }) => ({
          id: match.id,
          title: playlistTitle(match),
          league: match.league,
          status: match.status,
          kickoff: match.timestamp
            ? new Date(match.timestamp).toISOString()
            : null,
          quality: stream.quality,
          provider: stream.provider,
          resolution: stream.resolution || "direct",
          streamCheck:
            stream.streamCheck || "verified",
          url: stream.url,
        })),
      },
      null,
      2,
    )}\n`,
  );
  await writeFile(
    new URL("footyfootball-unavailable.json", OUTPUT_DIR),
    `${JSON.stringify(
      {
        source: "OgBek/footyLive-compatible public provider APIs",
        note: "Only direct media URLs or resolvable media manifests enter footyfootball.m3u.",
        count: unavailable.length,
        matches: unavailable.sort((a, b) => a.title.localeCompare(b.title)),
      },
      null,
      2,
    )}\n`,
  );

  console.log(
    `Generated ${entries.length} playable playlist entries from ${matches.length} football fixtures; ${unavailable.length} unavailable.`,
  );
}

main()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await browserInstance?.close().catch(() => {});
  });