export function parseConfiguration(configuration = '{}') {
    let cfg = {};
    try {
        if (configuration && configuration !== '{}') {
            cfg = JSON.parse(configuration);
        }
    } catch (e) {
        try {
            cfg = JSON.parse(decodeURIComponent(configuration));
        } catch (e2) {
            cfg = {};
        }
    }

    // Auto-fill credentials from environment if missing in URL
    if (!cfg.DebridApiKey && (!cfg.DebridServices || cfg.DebridServices.length === 0)) {
        const defaultProvider = process.env.DEFAULT_DEBRID_SERVICE || 'RealDebrid';
        const rdKey = process.env.REALDEBRID_API_KEY || process.env.RD_API_KEY;
        const adKey = process.env.ALLDEBRID_API_KEY;
        const tbKey = process.env.TORBOX_API_KEY;
        const pmKey = process.env.PREMIUMIZE_API_KEY;
        const dlKey = process.env.DEBRIDLINK_API_KEY;

        const services = [];
        if (rdKey) services.push({ provider: 'RealDebrid', apiKey: rdKey });
        if (adKey) services.push({ provider: 'AllDebrid', apiKey: adKey });
        if (tbKey) services.push({ provider: 'TorBox', apiKey: tbKey });
        if (pmKey) services.push({ provider: 'Premiumize', apiKey: pmKey });
        if (dlKey) services.push({ provider: 'DebridLink', apiKey: dlKey });

        if (services.length > 0) {
            cfg.DebridServices = services;
            cfg.DebridProvider = services[0].provider;
            cfg.DebridApiKey = services[0].apiKey;
        } else if (process.env.DEBRID_API_KEY) {
            cfg.DebridProvider = defaultProvider;
            cfg.DebridApiKey = process.env.DEBRID_API_KEY;
            cfg.DebridServices = [{ provider: defaultProvider, apiKey: process.env.DEBRID_API_KEY }];
        }
    }

    if (!cfg.Languages || cfg.Languages.length === 0) {
        cfg.Languages = ['en'];
    }
    if (!cfg.Resolutions || cfg.Resolutions.length === 0) {
        cfg.Resolutions = ['4k', '1080p', '720p'];
    }

    return cfg;
}
