export function localWorkspacePlatform() {
  return {
    loading: false,
    submitting: false,
    available: false,
    authRequired: false,
    context: null,
    capabilities: null,
    user: null,
    error: "",
    members: null,
    auditEvents: null,
    login: async () => undefined,
    logout: async () => undefined,
    reload: async () => false,
    loadMembers: async () => undefined,
    loadAudit: async () => undefined,
  };
}
