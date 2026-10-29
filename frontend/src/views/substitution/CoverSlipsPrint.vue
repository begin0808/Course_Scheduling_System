<script setup lang="ts">
// 代導通知單列印頁(v1.4.0):一位代導老師一張(A4 直式)。
// 代導以天為單位、和課表無關,所以不畫週課表,只列「哪一天、哪個時段、代哪一班、原導師是誰」。
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { ApiError } from '@/api/client'
import { getCoverSlips } from '@/api/homeroomCovers'
import type { CoverSlips } from '@/api/homeroomCovers'

const DAY_NAMES = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']

const route = useRoute()
const data = ref<CoverSlips | null>(null)
const error = ref('')
const loading = ref(true)

function doPrint() {
  window.print()
}
function doClose() {
  window.close()
}

onMounted(async () => {
  const sid = Number(route.query.semester_id)
  const ids = String(route.query.ids ?? '').split(',').map(Number).filter(Boolean)
  try {
    data.value = await getCoverSlips(sid, ids)
    if (!data.value.slips.length) error.value = '沒有已安排代導老師的日子'
  } catch (e) {
    error.value = (e as ApiError).message || '無法產生代導單'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="slips">
    <div class="no-print toolbar">
      <span v-if="data" class="hint">共 {{ data.slips.length }} 張</span>
      <button type="button" data-testid="slips-print" @click="doPrint">列印</button>
      <button type="button" @click="doClose">關閉</button>
    </div>

    <p v-if="loading" class="msg">載入中…</p>
    <p v-else-if="error" class="msg" data-testid="slips-error">{{ error }}</p>

    <section
      v-for="slip in data?.slips ?? []" :key="slip.teacher_name" class="page"
      data-testid="slip-cover"
    >
      <h1 class="school">{{ data?.school_name }}　代導　通知單</h1>
      <div class="meta">
        <span class="big" data-testid="slip-cover-teacher">代導教師：{{ slip.teacher_name }}</span>
        <span class="small">{{ data?.semester_label }}</span>
      </div>

      <table class="grid">
        <thead>
          <tr><th>日期</th><th>星期</th><th>時段</th><th>班級</th><th>原導師</th><th>假別</th></tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in slip.rows" :key="i" data-testid="slip-cover-row">
            <td>{{ r.date }}</td>
            <td>{{ DAY_NAMES[r.weekday - 1] }}</td>
            <td>{{ r.part_label }}</td>
            <td>{{ r.class_name }}</td>
            <td>{{ r.absent_teacher_name }}</td>
            <td>{{ r.leave_type_label }}</td>
          </tr>
        </tbody>
      </table>
      <p class="note">
        代導期間請協助班級的早自習、午休、導師時間與放學等班級事務。
      </p>
      <div class="sign">
        <span>代導教師簽收：＿＿＿＿＿＿＿＿</span>
        <span>教學組：＿＿＿＿＿＿＿＿</span>
      </div>
    </section>
  </div>
</template>

<style scoped>
.slips {
  color: #000;
  background: #fff;
  font-family: "DFKai-SB", "BiauKai", "標楷體", "Kaiti TC", serif;
}
.toolbar { display: flex; gap: 8px; justify-content: flex-end; align-items: center; padding: 16px 24px 0; }
.toolbar button {
  padding: 6px 16px; cursor: pointer; border: 1px solid #888; border-radius: 4px; background: #f4f4f4;
}
.hint { color: #555; font-size: 14px; }
.msg { text-align: center; padding: 40px 0; font-size: 15px; }
.page { max-width: 720px; margin: 0 auto; padding: 32px 24px; }
.page + .page { border-top: 1px dashed #bbb; }
.school { font-size: 22px; font-weight: normal; text-align: center; margin: 0 0 18px; }
.meta { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 14px; }
.big { font-size: 19px; }
.small { font-size: 13px; }
.grid { width: 100%; border-collapse: collapse; border: 4px double #000; }
.grid th, .grid td {
  border: 1px solid #000; text-align: center; padding: 8px 6px; font-size: 15px;
}
.grid th { font-weight: normal; border-bottom-width: 2px; }
.note { font-size: 13px; margin: 10px 0 0; }
.sign { display: flex; justify-content: space-between; margin-top: 36px; font-size: 15px; }

@media print {
  @page { size: A4 portrait; margin: 12mm; }
  .no-print { display: none !important; }
  .page { max-width: none; padding: 0; break-after: page; }
  .page + .page { border-top: none; }
  .page:last-child { break-after: auto; }
}
</style>
