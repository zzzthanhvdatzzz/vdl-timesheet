'use strict';
// Kiểm tra launcher bằng dịch vụ giả lập; không mở tunnel hoặc dùng dữ liệu thật.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {EventEmitter} = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'tunnel.js'), 'utf8');

async function run(root, assignedName) {
  const requests = [], exits = [], logs = [], errors = [];
  const signals = {};
  let closed = false;
  let startupCallback;
  const mockLocaltunnel = async options => {
    requests.push(options);
    const fakeTunnel = new EventEmitter();
    fakeTunnel.close = () => { closed = true; fakeTunnel.emit('close'); };
    const selected = Array.isArray(assignedName) ? assignedName[requests.length - 1] : assignedName;
    fakeTunnel.url = `https://${selected || options.subdomain}.loca.lt`;
    setImmediate(() => fakeTunnel.emit('url', fakeTunnel.url));
    return fakeTunnel;
  };
  const mockHttps = {
    get(url, callback) {
      const request = new EventEmitter();
      request.setTimeout = () => {};
      request.destroy = () => {};
      setImmediate(() => {
        const response = new EventEmitter();
        response.statusCode = 200;
        callback(response);
        response.emit('data', '192.0.2.1');
        response.emit('end');
      });
      return request;
    }
  };
  vm.runInNewContext(source, {
    __dirname: root,
    require(name) {
      if (name === './vendor/localtunnel/node_modules/localtunnel') return mockLocaltunnel;
      if (name === 'https') return mockHttps;
      return require(name);
    },
    process: {argv: ['node', 'tunnel.js', '8000'], env: {},
      on(name, fn) { signals[name] = fn; }, exit(code) { exits.push(code); }},
    console: {log(message) { logs.push(message); }, error(message) { errors.push(message); }},
    URL,
    setTimeout(callback, delay) {
      if (delay === 60000) startupCallback = callback;
      else setImmediate(requests.length >= 2 ? startupCallback : callback);
      return {};
    }, clearTimeout() {}
  });
  for (let i = 0; i < 16; i++) await new Promise(resolve => setImmediate(resolve));
  return {requests, exits, logs, errors, stopped: () => closed, stop: () => signals.SIGINT()};
}

test('Mỗi lần khởi động đọc cùng tên đã lưu, hỗ trợ file Notepad BOM/CRLF', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vdl-tunnel-'));
  try {
    fs.writeFileSync(path.join(root, 'TEN_LINK_PUBLIC.txt'), '\uFEFFChamCong-VDL-VN\r\n');
    for (let i = 0; i < 2; i++) {
      const result = await run(root);
      assert.equal(result.requests.length, 1);
      assert.equal(result.requests[0].subdomain, 'chamcong-vdl-vn');
      assert.equal(result.requests[0].local_host, '127.0.0.1');
      const linkFile = path.join(root, 'data', 'public-link.txt');
      assert.match(fs.readFileSync(linkFile, 'utf8'), /^LINK PUBLIC: https:\/\/chamcong-vdl-vn\.loca\.lt\n/);
      assert.equal(result.exits.length, 0);
      result.stop();
      assert.equal(result.stopped(), true);
      assert.equal(result.exits[0], 0);
      assert.equal(fs.existsSync(linkFile), false);
    }
  } finally { fs.rmSync(root, {recursive: true, force: true}); }
});

test('Không chấp nhận hoặc xuất bản URL ngẫu nhiên khi tên yêu cầu không được cấp', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vdl-tunnel-'));
  try {
    fs.writeFileSync(path.join(root, 'TEN_LINK_PUBLIC.txt'), 'chamcong-vdl-vn');
    fs.mkdirSync(path.join(root, 'data'));
    const linkFile = path.join(root, 'data', 'public-link.txt');
    fs.writeFileSync(linkFile, 'old link');
    const result = await run(root, 'random-fallback');
    assert.equal(result.requests[0].subdomain, 'chamcong-vdl-vn');
    assert.equal(result.exits[0], 1);
    assert.equal(result.stopped(), true);
    assert.equal(fs.existsSync(linkFile), false);
    assert.match(result.errors.join('\n'), /Khong duoc cap dung link/);
    assert.equal(result.logs.some(log => log.startsWith('\nLINK PUBLIC:')), false);
  } finally { fs.rmSync(root, {recursive: true, force: true}); }
});

test('Thiếu hoặc sai tên link thì báo lỗi trước khi gọi LocalTunnel', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vdl-tunnel-'));
  try {
    let result = await run(root);
    assert.equal(result.requests.length, 0);
    assert.equal(result.exits[0], 1);
    assert.match(result.errors[0], /Thieu TEN_LINK_PUBLIC/);
    fs.writeFileSync(path.join(root, 'TEN_LINK_PUBLIC.txt'), 'https://example.loca.lt');
    result = await run(root);
    assert.equal(result.requests.length, 0);
    assert.equal(result.exits[0], 1);
    assert.match(result.errors[0], /khong dien ca URL/);
  } finally { fs.rmSync(root, {recursive: true, force: true}); }
});

test('Thử lại cùng tên khi phiên cũ chưa nhả tên, chỉ công bố link đúng', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vdl-tunnel-'));
  try {
    fs.writeFileSync(path.join(root, 'TEN_LINK_PUBLIC.txt'), 'chamcong-vdl-vn');
    const result = await run(root, ['random-fallback', 'chamcong-vdl-vn']);
    assert.equal(result.requests.length, 2);
    assert.ok(result.requests.every(options => options.subdomain === 'chamcong-vdl-vn'));
    assert.equal(result.exits.length, 0);
    assert.match(fs.readFileSync(path.join(root, 'data', 'public-link.txt'), 'utf8'), /^LINK PUBLIC: https:\/\/chamcong-vdl-vn\.loca\.lt\n/);
    result.stop();
  } finally { fs.rmSync(root, {recursive: true, force: true}); }
});
