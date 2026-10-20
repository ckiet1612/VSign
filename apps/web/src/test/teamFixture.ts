export const teamUser = {id:'admin',email:'admin@example.com',display_name:'Admin',role:'admin' as const};
export const teamOverview = () => ({api_version:'1' as const,workspace_id:'local',permissions:{manage:true},
  grantable_roles:['operator','reviewer','viewer'] as ('operator'|'reviewer'|'viewer')[],counts:{active:1,suspended:0,removed:0},
  members:[{id:'admin',email:'admin@example.com',display_name:'Admin',role:'admin' as const,status:'active' as const,
    active:true,revision:0,protected:true,created_at:'2026-10-16T00:00:00Z'}],next_cursor:null});
export const teamInvitations = () => ({api_version:'1' as const,workspace_id:'local',invitations:[],next_cursor:null});
export const teamRoles = () => ({api_version:'1' as const,workspace_id:'local',roles:[{id:'admin',permissions:['members:manage']}]});
export const teamEvents = () => ({api_version:'1' as const,workspace_id:'local',events:[],next_cursor:null});
