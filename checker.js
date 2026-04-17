const fs = require('fs');
const net = require('net');
const { URL } = require('url');

// Парсинг VLESS URL
function parseVlessUrl(vlessUrl) {
  try {
    const url = new URL(vlessUrl);
    if (url.protocol !== 'vless:') return null;

    const uuid = url.username;
    const address = url.hostname;
    const port = parseInt(url.port) || 443;

    const params = {};
    url.searchParams.forEach((value, key) => {
      params[key] = value;
    });

    return {
      uuid,
      address,
      port,
      network: params.type || 'tcp',
      path: params.path || '/',
      host: params.host || address,
      tls: params.security === 'tls' || params.security === 'reality',
      sni: params.sni || address,
      name: decodeURIComponent(url.hash.slice(1)) || address
    };
  } catch (e) {
    return null;
  }
}

// Проверка доступности сервера
function checkServer(config, timeout = 5000) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    let isResolved = false;

    const timer = setTimeout(() => {
      if (!isResolved) {
        isResolved = true;
        socket.destroy();
        resolve(false);
      }
    }, timeout);

    socket.connect(config.port, config.address, () => {
      if (!isResolved) {
        isResolved = true;
        clearTimeout(timer);
        socket.destroy();
        resolve(true);
      }
    });

    socket.on('error', () => {
      if (!isResolved) {
        isResolved = true;
        clearTimeout(timer);
        socket.destroy();
        resolve(false);
      }
    });
  });
}

// Основная функция проверки
async function checkSubscription() {
  console.log('🔍 Starting VLESS checker...\n');

  // Читаем файл с подпиской
  let subscriptionData;
  try {
    subscriptionData = JSON.parse(fs.readFileSync('subscription.json', 'utf8'));
  } catch (e) {
    console.error('❌ Error reading subscription.json:', e.message);
    console.log('\n💡 Create subscription.json file with format:');
    console.log('{"urls": ["vless://...", "vless://..."]}');
    return;
  }

  const urls = subscriptionData.urls || [];
  console.log(`📋 Found ${urls.length} VLESS configs\n`);

  const workingConfigs = [];
  const failedConfigs = [];

  for (let i = 0; i < urls.length; i++) {
    const url = urls[i];
    const config = parseVlessUrl(url);

    if (!config) {
      console.log(`⚠️  [${i + 1}/${urls.length}] Invalid URL format`);
      failedConfigs.push(url);
      continue;
    }

    process.stdout.write(`⏳ [${i + 1}/${urls.length}] Checking ${config.name} (${config.address}:${config.port})... `);

    const isWorking = await checkServer(config, 5000);

    if (isWorking) {
      console.log('✅ WORKING');
      workingConfigs.push(url);
    } else {
      console.log('❌ FAILED');
      failedConfigs.push(url);
    }
  }

  // Сохраняем результаты
  const results = {
    checked_at: new Date().toISOString(),
    total: urls.length,
    working: workingConfigs.length,
    failed: failedConfigs.length,
    working_configs: workingConfigs,
    failed_configs: failedConfigs
  };

  fs.writeFileSync('results.json', JSON.stringify(results, null, 2));
  fs.writeFileSync('working.txt', workingConfigs.join('\n'));

  console.log('\n' + '='.repeat(50));
  console.log(`✅ Working: ${workingConfigs.length}/${urls.length}`);
  console.log(`❌ Failed: ${failedConfigs.length}/${urls.length}`);
  console.log('='.repeat(50));
  console.log('\n📁 Results saved to:');
  console.log('  - results.json (full report)');
  console.log('  - working.txt (working configs only)');
}

// Запуск
checkSubscription().catch(console.error);
