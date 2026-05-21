/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { HouseholdInfo } from './HouseholdInfo';
import type { MemberInfo } from './MemberInfo';
export type HouseholdSessionResponse = {
    token: string;
    locale: string;
    household: HouseholdInfo;
    member: MemberInfo;
};

