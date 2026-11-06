// This adapter is public. Local installation embeds its binding after a private legacy generator.
function main(config) {
  const owned = new Set(agentrouteManaged.ownedAliases);
  const prefix = '🌐固定出口 · ';
  config.proxies = (config.proxies || []).filter(p => {
    if (p['agentroute-generated'] === true || owned.has(p.name)) return false;
    if (p.name && p.name.indexOf(prefix) === 0) throw new Error('Ambiguous fixed-exit name: review source ownership');
    return true;
  });
  config = legacyMain(config);
  const group = routingData.group;
  const originals = new Set(config.proxies.filter(p => p.name.indexOf(prefix) !== 0).map(p => p.name));
  for (const p of config.proxies) {
    if (p.name.indexOf(prefix) === 0) {
      if (p['dialer-proxy'] !== p.name.slice(prefix.length) || !originals.has(p['dialer-proxy'])) throw new Error('Invalid generated chain');
      p['agentroute-generated'] = true;
    }
  }
  config['rule-providers'] = config['rule-providers'] || {};
  for (const id of ['private','reject','proxy','direct','cn-ip']) {
    config['rule-providers']['agentroute-' + id] = {
      type:'file', behavior:id === 'cn-ip' ? 'ipcidr' : 'domain', format:'yaml',
      path:'./rules/agent-route/generations/' + agentrouteManaged.generation + '/mihomo/' + id + '.yaml'
    };
  }
  const domestic = ['https://dns.alidns.com/dns-query#DIRECT','https://doh.pub/dns-query#DIRECT'];
  const overseas = ['https://1.1.1.1/dns-query#' + group,'https://8.8.8.8/dns-query#' + group];
  const nodeRules = [], nodeDomains = [], seen = new Set();
  for (const p of config.proxies) {
    const host = p.server;
    if (!host || seen.has(host)) continue;
    seen.add(host);
    if (/^\d{1,3}(\.\d{1,3}){3}$/.test(host)) nodeRules.push('IP-CIDR,'+host+'/32,DIRECT,no-resolve');
    else if (host.indexOf(':') >= 0) nodeRules.push('IP-CIDR6,'+host+'/128,DIRECT,no-resolve');
    else { nodeRules.push('DOMAIN,'+host+',DIRECT'); nodeDomains.push(host); }
  }
  const lan = routingData.lanRules.filter(r => r !== 'IP-CIDR,198.18.0.0/16,DIRECT,no-resolve');
  const protectedRules = [];
  for (const host of agentrouteManaged.protectedHosts || []) {
    protectedRules.push('AND,((NETWORK,UDP),(DOMAIN,'+host+')),REJECT');
    protectedRules.push('DOMAIN,'+host+','+group);
  }
  config.rules = protectedRules.concat(nodeRules, lan, [
    'DOMAIN,dns.alidns.com,DIRECT','DOMAIN,doh.pub,DIRECT',
    'RULE-SET,agentroute-private,DIRECT','RULE-SET,agentroute-reject,REJECT',
    'AND,((NETWORK,UDP),(RULE-SET,agentroute-proxy)),REJECT',
    'RULE-SET,agentroute-proxy,'+group,'RULE-SET,pluwen-china-domain,DIRECT',
    'RULE-SET,agentroute-direct,DIRECT','RULE-SET,agentroute-cn-ip,DIRECT',
    'NETWORK,UDP,REJECT','MATCH,'+group
  ]);
  const policy = {};
  for (const host of agentrouteManaged.protectedHosts || []) policy[host] = overseas;
  for (const host of nodeDomains) policy[host] = domestic;
  policy['+.lan,+.local,+.localhost,+.internal,+.arpa'] = ['system'];
  policy['rule-set:agentroute-private'] = ['system'];
  policy['rule-set:agentroute-reject,agentroute-proxy'] = overseas;
  policy['rule-set:pluwen-china-domain,agentroute-direct'] = domestic;
  config.dns['nameserver-policy'] = policy;
  config.dns['default-nameserver'] = ['https://223.5.5.5/dns-query#DIRECT','https://223.6.6.6/dns-query#DIRECT'];
  config.dns['direct-nameserver-follow-policy'] = true;
  return config;
}
