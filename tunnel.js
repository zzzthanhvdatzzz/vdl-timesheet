'use strict';
const localtunnel = require('./vendor/localtunnel/node_modules/localtunnel');
const https = require('https');
const fs = require('fs');
const path = require('path');
const port = Number(process.argv[2] || process.env.PORT || 8000);
const nameFile = path.join(__dirname, 'TEN_LINK_PUBLIC.txt');
const linkFile = path.join(__dirname, 'data', 'public-link.txt');
let tunnel;
let startupTimeout;
let stopping = false;

function requestedName() {
  let name;
  try {
    name = fs.readFileSync(nameFile, 'utf8').replace(/^\uFEFF/, '').trim().toLowerCase();
  } catch (_) {
    throw new Error('Thieu TEN_LINK_PUBLIC.txt. Hay giai nen day du ban cap nhat.');
  }
  if (!/^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$/.test(name)) {
    throw new Error('TEN_LINK_PUBLIC.txt phai chua mot ten 3-63 ky tu: chu khong dau a-z, so, dau gach ngang; khong dien ca URL.');
  }
  return name;
}

function password() {
  return new Promise(resolve => {
    const request = https.get('https://loca.lt/mytunnelpassword', response => {
      let value = '';
      response.on('data', chunk => { if (value.length < 256) value += chunk.toString(); });
      response.on('end', () => resolve(response.statusCode === 200 && /^[0-9a-fA-F:.]+$/.test(value.trim()) ? value.trim() : ''));
      response.on('error', () => resolve(''));
    });
    request.setTimeout(10000, () => request.destroy());
    request.on('error', () => resolve(''));
  });
}
function cleanUp() {
  try { fs.unlinkSync(linkFile); } catch (_) {}
}
function stop(code, message) {
  if (stopping) return;
  stopping = true;
  clearTimeout(startupTimeout);
  if (message) console.error(message);
  cleanUp();
  if (tunnel) tunnel.close();
  process.exit(code);
}
(async () => {
  cleanUp();
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Cong phai la so tu 1 den 65535.');
  const subdomain = requestedName();
  const expectedUrl = `https://${subdomain}.loca.lt`;
  console.log(`Dang yeu cau dung link: ${expectedUrl}`);
  let nameUnavailable = false;
  startupTimeout = setTimeout(() => stop(1,
    nameUnavailable
      ? `Khong duoc cap dung link ${expectedUrl} sau 60 giay. Ten co the van dang duoc su dung. Dong tunnel cu, cho mot luc roi thu lai. Chuong trinh khong tu doi sang link khac.`
      : 'LocalTunnel chua ket noi duoc sau 60 giay. Kiem tra Internet, dong tunnel cu roi thu lai.'), 60000);
  while (!stopping) {
    const candidate = await localtunnel({port, local_host: '127.0.0.1', subdomain});
    if (stopping) { candidate.close(); return; }
    // Một kết nối trong nhóm tunnel có thể báo lỗi sau khi candidate đã đóng.
    candidate.on('error', error => {
      if (candidate === tunnel) stop(1, 'LocalTunnel: ' + error.message);
    });
    const assigned = new URL(candidate.url);
    if (assigned.origin === expectedUrl && assigned.pathname === '/' && !assigned.search && !assigned.hash && !assigned.username && !assigned.password) {
      tunnel = candidate;
      nameUnavailable = false;
      break;
    }
    candidate.close();
    nameUnavailable = true;
    console.log('Ten link chua san sang. Dang yeu cau lai dung ten sau 5 giay; khong dung link ngau nhien.');
    await new Promise(resolve => setTimeout(resolve, 5000));
  }
  if (stopping) return;
  tunnel.on('close', () => stop(1, 'LocalTunnel da dong. Chay lai de yeu cau cung ten link.'));
  await new Promise(resolve => tunnel.once('url', resolve));
  clearTimeout(startupTimeout);
  const value = await password();
  if (stopping) return;
  const text = `LINK PUBLIC: ${expectedUrl}\nTunnel Password: ${value || 'Mo https://loca.lt/mytunnelpassword tren may nay de lay'}\nGiu may bat, co Internet va khong Sleep de link hoat dong.\n`;
  fs.mkdirSync(path.dirname(linkFile), {recursive: true});
  fs.writeFileSync(linkFile, text, 'utf8');
  console.log('\n' + text);
})().catch(error => stop(1, 'Khong tao duoc LocalTunnel: ' + error.message));
process.on('SIGINT', () => stop(0));
