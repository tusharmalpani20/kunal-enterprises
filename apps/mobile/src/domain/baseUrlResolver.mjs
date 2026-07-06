const SMOKE_METHOD = 'kunal_enterprises.api.health.smoke';
const HEALTH_TIMEOUT_MS = 4000;

export async function resolveBaseUrl({ primary, fallback, probe }) {
  console.log(`[baseUrl] resolving — primary: ${primary}, fallback: ${fallback || 'none'}`);
  try {
    const result = await probe(primary, SMOKE_METHOD, HEALTH_TIMEOUT_MS);
    console.log(`[baseUrl] primary reachable — using ${primary}`);
    console.log(`[baseUrl] smoke response:`, JSON.stringify(result?.data?.message ?? result?.message ?? result).slice(0, 300));
    return primary;
  } catch (error) {
    console.log(`[baseUrl] primary unreachable: ${error?.message || error}`);
    if (!fallback) {
      console.log(`[baseUrl] no fallback configured — using primary ${primary}`);
      return primary;
    }
    try {
      const result = await probe(fallback, SMOKE_METHOD, HEALTH_TIMEOUT_MS);
      console.log(`[baseUrl] fallback reachable — using ${fallback}`);
      console.log(`[baseUrl] smoke response:`, JSON.stringify(result?.data?.message ?? result?.message ?? result).slice(0, 300));
      return fallback;
    } catch (fallbackError) {
      console.log(`[baseUrl] fallback also unreachable: ${fallbackError?.message || fallbackError}`);
      console.log(`[baseUrl] defaulting to primary ${primary}`);
      return primary;
    }
  }
}
