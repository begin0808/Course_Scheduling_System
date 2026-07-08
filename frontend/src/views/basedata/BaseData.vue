<script setup lang="ts">
import { NAlert, NSelect, NSpace, NTabPane, NTabs } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'
import ClassesTab from './ClassesTab.vue'
import ImportTab from './ImportTab.vue'
import RoomsTab from './RoomsTab.vue'
import SubjectsTab from './SubjectsTab.vue'
import TeachersTab from './TeachersTab.vue'

const semesters = ref<SemesterListItem[]>([])
const currentId = ref<number | null>(null)

const semesterOptions = computed(() =>
  semesters.value.map((s) => ({ label: s.label, value: s.id })),
)

onMounted(async () => {
  semesters.value = await listSemesters()
  if (semesters.value.length) currentId.value = semesters.value[0].id
})
</script>

<template>
  <n-space vertical size="large">
    <n-space align="center">
      <h1 style="margin: 0">基礎資料</h1>
      <n-select
        v-model:value="currentId"
        :options="semesterOptions"
        placeholder="選擇學期"
        style="width: 240px"
      />
    </n-space>

    <n-alert v-if="!currentId" type="info">
      請先於「學期與節次表」建立學期,再回此頁維護教師、班級、科目與場地。
    </n-alert>

    <n-tabs v-else type="line" animated>
      <n-tab-pane name="teachers" tab="教師">
        <TeachersTab :key="`t-${currentId}`" :semester-id="currentId" />
      </n-tab-pane>
      <n-tab-pane name="classes" tab="班級">
        <ClassesTab :key="`c-${currentId}`" :semester-id="currentId" />
      </n-tab-pane>
      <n-tab-pane name="subjects" tab="科目">
        <SubjectsTab :key="`s-${currentId}`" :semester-id="currentId" />
      </n-tab-pane>
      <n-tab-pane name="rooms" tab="場地">
        <RoomsTab :key="`r-${currentId}`" :semester-id="currentId" />
      </n-tab-pane>
      <n-tab-pane name="import" tab="批次匯入">
        <ImportTab :key="`i-${currentId}`" :semester-id="currentId" />
      </n-tab-pane>
    </n-tabs>
  </n-space>
</template>
