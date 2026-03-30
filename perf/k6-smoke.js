import http from 'k6/http';
import { check, sleep } from 'k6';


export const options = {
  vus: 1,
  iterations: 1,
  thresholds: {
    checks: ['rate==1.0'],
    http_req_failed: ['rate==0'],
  },
};


const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:4173';
const USERNAME = __ENV.K6_USERNAME || 'admin@example.com';
const PASSWORD = __ENV.K6_PASSWORD || 'LaunchPilot!123';


export default function () {
  const health = http.get(`${BASE_URL}/health`);
  check(health, {
    'health is 200': (response) => response.status === 200,
    'health reports ok': (response) => response.body.includes('"status":"ok"'),
  });

  const loginPage = http.get(`${BASE_URL}/login`);
  const csrfMatch = loginPage.body.match(/name="csrf_token" value="([^"]+)"/);
  check(loginPage, {
    'login page is 200': (response) => response.status === 200,
    'login page has csrf token': () => Boolean(csrfMatch),
  });

  const loginResponse = http.post(
    `${BASE_URL}/login`,
    {
      username: USERNAME,
      password: PASSWORD,
      next: '/tms/',
      csrf_token: csrfMatch ? csrfMatch[1] : '',
    },
    {
      redirects: 0,
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
    },
  );
  check(loginResponse, {
    'login redirects': (response) => response.status === 302,
  });

  const dashboard = http.get(`${BASE_URL}/tms/`);
  check(dashboard, {
    'dashboard is 200': (response) => response.status === 200,
    'dashboard contains shipments': (response) => response.body.includes('Recent Shipments'),
  });

  sleep(1);
}
