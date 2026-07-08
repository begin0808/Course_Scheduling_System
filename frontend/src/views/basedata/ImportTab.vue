<script setup lang="ts">
import {
  NAlert, NButton, NCheckbox, NList, NListItem, NRadioButton, NRadioGroup, NSpace, NText, NUpload,
  useMessage,
} from 'naive-ui'
import type { UploadFileInfo } from 'naive-ui'
import { computed, ref } from 'vue'
import { ENTITY_LABELS, downloadTemplate, uploadImport } from '@/api/imports'
import type { ImportEntity, ImportResult } from '@/api/imports'

const props = defineProps<{ semesterId: number }>()
const emit = defineEmits<{ imported: [] }>()
const message = useMessage()

const entity = ref<ImportEntity>('subjects')
const createAccounts = ref(false)
const selectedFile = ref<File | null>(null)
const uploading = ref(false)
const result = ref<ImportResult | null>(null)

const isTeacher = computed(() => entity.value === 'teachers')

async function onDownload() {
  try {
    await downloadTemplate(entity.value)
  } catch {
    message.error('範本下載失敗')
  }
}

function onFileChange(data: { fileList: UploadFileInfo[] }) {
  selectedFile.value = data.fileList[0]?.file ?? null
  result.value = null
}

async function onUpload() {
  if (!selectedFile.value) {
    message.warning('請先選擇檔案')
    return
  }
  uploading.value = true
  result.value = null
  try {
    const r = await uploadImport(
      entity.value, props.semesterId, selectedFile.value, isTeacher.value && createAccounts.value,
    )
    result.value = r
    if (r.errors.length === 0) {
      message.success(`成功匯入 ${r.imported} 筆`)
      emit('imported')
    } else {
      message.error('匯入未完成,請修正錯誤後重試')
    }
  } catch (e) {
    message.error((e as Error).message || '匯入失敗')
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <n-space vertical size="large" style="max-width: 640px">
    <n-alert type="info" :show-icon="true">
      匯入步驟:① 選擇資料類型 → ② 下載範本並填寫(第 4 列起填,說明/範例列會自動略過)→ ③ 上傳。
      任一列有誤將全部不匯入,並列出錯誤列號。
    </n-alert>

    <n-space vertical>
      <n-text strong>① 資料類型</n-text>
      <n-radio-group v-model:value="entity">
        <n-radio-button v-for="(label, key) in ENTITY_LABELS" :key="key" :value="key">
          {{ label }}
        </n-radio-button>
      </n-radio-group>
    </n-space>

    <n-space vertical>
      <n-text strong>② 下載範本</n-text>
      <n-button @click="onDownload">下載「{{ ENTITY_LABELS[entity] }}」範本</n-button>
    </n-space>

    <n-space vertical>
      <n-text strong>③ 上傳填好的檔案</n-text>
      <n-checkbox v-if="isTeacher" v-model:checked="createAccounts">
        同時建立教師登入帳號(預設密碼,首次登入需更改)
      </n-checkbox>
      <n-upload :max="1" :default-upload="false" accept=".xlsx" @change="onFileChange">
        <n-button>選擇檔案</n-button>
      </n-upload>
      <n-button type="primary" :loading="uploading" :disabled="!selectedFile" @click="onUpload">
        開始匯入
      </n-button>
    </n-space>

    <n-alert v-if="result && result.errors.length === 0" type="success">
      成功匯入 {{ result.imported }} 筆資料。
    </n-alert>
    <n-alert v-if="result && result.errors.length > 0" type="error" title="匯入失敗(資料庫未寫入)">
      <n-list>
        <n-list-item v-for="(err, i) in result.errors" :key="i">
          <n-text>{{ err }}</n-text>
        </n-list-item>
      </n-list>
    </n-alert>
  </n-space>
</template>
