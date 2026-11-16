import { AtomicStateStore } from './atomic-state-store.mjs';
import { validateSettings } from './telegram-settings.mjs';
export class SettingsStore extends AtomicStateStore {
  transact(mutator) {
    return super.transact(async candidate=>{
      const replacement=await mutator(candidate),next=replacement===undefined?candidate:replacement;
      validateSettings(next);return next;
    });
  }
}
