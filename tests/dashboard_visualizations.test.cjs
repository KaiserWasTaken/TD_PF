const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const html = fs.readFileSync(
  path.join(__dirname, '..', 'api', 'static', 'autoridades.html'),
  'utf8',
)

test('authority dashboard connects trend, roadway, and hour-day visualizations', () => {
  assert.match(html, /id="graficaTendencia"/)
  assert.match(html, /conPeriodo\('\/api\/autoridades\/tendencia'\)/)
  assert.match(html, /id="graficaVialidades"/)
  assert.match(html, /id="matrizHoraDia"/)
  assert.match(html, /conPeriodo\('\/api\/autoridades\/matriz-hora-dia'\)/)
})
