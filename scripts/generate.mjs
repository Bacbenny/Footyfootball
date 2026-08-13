import { mkdir, writeFile } from "node:fs/promises";

const SOURCES = {
  watchFooty: "https://api.watchfooty.st",
  cdnLive:
    "https://api.cdnlivetv.tv/api/v1/events/sports/?user=cdnlivetv&plan=free",
  streamedMatches: "https://streamed.pk/api/matches/football",
  streamedStream: "https://streamed.pk/api/stream",
};

const OUTPUT_DIR = new URL("../output/", import.meta.url);
const TIMEOUT_MS = 8_000;
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

function statusFor(match) {
  const timestamp = Number(match?.timestamp || 0);
  const now = Date.now();
  const explicit = ["in", "live"].includes(text(match?.status).toLowerCase());
  const withinLiveWindow =
    timestamp > 0 && now >= timestamp && now - timestamp < 125 * 60 * 1000;
  return explicit || withinLiveWindow ? "live" : "upcoming";
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

function escapeAttribute(value) {
  return text(value).replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}

function playlistTitle(match) {
  const prefix = match.status === "live" ? "[LIVE] " : "";
  return `${prefix}${match.home} vs ${match.away}`;
}

function toExtInf(match, candidate) {
  const title = playlistTitle(match);
  const attrs = [
    `tvg-id="footy-${escapeAttribute(match.id)}"`,
    `tvg-name="${escapeAttribute(title)}"`,
    `group-title="${escapeAttribute(match.league)}"`,
  ];
  if (match.homeLogo) attrs.push(`tvg-logo="${escapeAttribute(match.homeLogo)}"`);
  return `#EXTINF:-1 ${attrs.join(" ")},${title} | ${candidate.quality}`;
}

async function main() {
  const matches = await getWatchFootyMatches();
  const cdnData = await safeFetch(SOURCES.cdnLive, {});
  const streamedMatches = await safeFetch(SOURCES.streamedMatches, []);
  const entries = [];
  const seenMatchIds = new Set();

  for (const match of matches) {
    if (!match.id || seenMatchIds.has(match.id)) continue;
    seenMatchIds.add(match.id);
    const candidates = [];

    await addWatchFootyCandidates(match, candidates);
    await addCdnLiveCandidates(match, candidates, cdnData);
    await addStreamedCandidates(match, candidates, streamedMatches);

    candidates.sort((a, b) => b.score - a.score);
    const best = candidates[0];
    if (!best) continue;

    entries.push({
      match,
      stream: best,
    });
  }

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
          url: stream.url,
        })),
      },
      null,
      2,
    )}\n`,
  );

  console.log(
    `Generated ${entries.length} playlist entries from ${matches.length} football fixtures.`,
  );
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});