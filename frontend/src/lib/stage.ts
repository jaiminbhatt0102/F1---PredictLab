export function stageLabel(stage: string): string {
  return ({
    upcoming: 'Before qualifying',
    qualifying_complete_sprint_pending: 'Qualifying done, sprint to come',
    qualifying_complete: 'Qualifying done, race to come',
    race_complete: 'Race finished',
  } as Record<string, string>)[stage] ?? stage
}
