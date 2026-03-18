<script setup lang="ts">
import { provide, toRefs } from 'vue';
import { pdfEngineKey } from '../context/pdf-engine-context';
import type { PdfEngine } from '@embedpdf/models';

interface Props {
  engine: PdfEngine | null;
  isLoading: boolean;
  error: Error | null;
}

const props = defineProps<Props>();

// Convert props to refs and provide them
const { engine, isLoading, error } = toRefs(props);

provide(pdfEngineKey, {
  engine,
  isLoading,
  error,
});
</script>

<template>
  <slot />
</template>
