import type { WorkspaceRole, AuthenticatedUser } from './workspace';

export type GrantableRole = Exclude<WorkspaceRole, 'owner'>;
export type MemberStatus = 'active' | 'suspended' | 'removed';
export type TeamTab = 'members' | 'roles' | 'invitations' | 'audit';
export interface TeamMember {
  id:string; email:string; display_name:string; role:AuthenticatedUser['role']; status:MemberStatus;
  active:boolean; revision:number; protected:boolean; created_at:string;
}
export interface TeamOverview {
  api_version:'1'; workspace_id:string; permissions:{manage:boolean}; grantable_roles:GrantableRole[];
  counts:Record<MemberStatus,number>; members:TeamMember[]; next_cursor:string|null;
}
export interface TeamRole {id:AuthenticatedUser['role']; permissions:string[]}
export interface TeamInvitation {
  id:string; email:string; role:GrantableRole; status:'pending'|'accepted'|'expired'|'revoked';
  created_by:string; created_at:string; expires_at:string;
}
export const teamActions = ['permission.member_updated','permission.invitation_created',
  'permission.invitation_revoked','permission.invitation_accepted','permission.denied'] as const;
export type TeamActionName = typeof teamActions[number];
export interface TeamChange {role?:AuthenticatedUser['role']; status?:MemberStatus; email?:string; member_id?:string}
export interface TeamEvent {
  id:string; action:TeamActionName; actor_id:string|null; member_id:string|null; resource_id:string|null;
  outcome:'success'|'failure'; created_at:string; before:TeamChange|null; after:TeamChange|null;
}
export interface TeamSnapshot {
  overview:TeamOverview; roles:TeamRole[]; invitations:TeamInvitation[]; events:TeamEvent[]; next_cursor:string|null;
}
export interface InvitationDetails {
  api_version:'1'; workspace_id:string; workspace_name:string; email:string; role:GrantableRole;
  expires_at:string; existing_account:boolean; auth_mode:'session'|'local_admin';
}
