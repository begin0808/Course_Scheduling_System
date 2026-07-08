import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getWizardState, updateWizardState } from '@/api/wizard'
import type { WizardState } from '@/api/wizard'

export const useWizardStore = defineStore('wizard', () => {
  const state = ref<WizardState | null>(null)
  const loaded = ref(false)

  async function fetch(): Promise<void> {
    try {
      state.value = await getWizardState()
    } catch {
      state.value = null
    } finally {
      loaded.value = true
    }
  }

  async function patch(body: Parameters<typeof updateWizardState>[0]): Promise<void> {
    state.value = await updateWizardState(body)
  }

  return { state, loaded, fetch, patch }
})
