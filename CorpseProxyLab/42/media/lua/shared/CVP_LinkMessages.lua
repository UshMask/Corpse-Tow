local messages={
    ['equipment operation pending']='IGUI_CVP_SaveBusy',
    ['player disconnected']='IGUI_CVP_PlayerDisconnected',
    ['rope exhausted']='IGUI_CVP_RopeExhausted',['shared rope']='IGUI_CVP_SharedRopeExtend',
    ['towing disabled']='IGUI_CVP_TowingDisabled',['not owner']='IGUI_CVP_OtherOwner',
    ['stop vehicle']='IGUI_CVP_StopVehicle',['material unavailable']='IGUI_CVP_NeedGear',
    ['first endpoint moved']='IGUI_CVP_BodyMoved',['stale connection']='IGUI_CVP_ConnectionChanged',
    ['attachment expired']='IGUI_CVP_QueueTimeout',['endpoint not reachable']='IGUI_CVP_NoPath',
    ['target not reachable']='IGUI_CVP_NoPath',['endpoint unloaded']='IGUI_CVP_Unavailable',
    ['unloaded endpoint']='IGUI_CVP_Unavailable',['body unavailable']='IGUI_CVP_Unavailable',
    ['body not found']='IGUI_CVP_Unavailable',['body unloaded']='IGUI_CVP_Unavailable',
    ['body not towable']='IGUI_CVP_Unavailable',['body identity mismatch']='IGUI_CVP_Unavailable',
    ['body identity ambiguous']='IGUI_CVP_Unavailable',
    ['body in use']='IGUI_CVP_LetGo',['vehicle unavailable']='IGUI_CVP_VehicleUnavailable',
    ['leave vehicle or unavailable player']='IGUI_CVP_LeaveVehicle',
    ['player bodies disabled']='IGUI_CVP_PlayerBodiesDisabled',['chain limit']='IGUI_CVP_VehicleLimit',
    ['two vehicles']='IGUI_CVP_LinkTwoCars',['loop']='IGUI_CVP_LinkLoop',
    ['body branch']='IGUI_CVP_LinkFullBody',['too far']='IGUI_CVP_LinkTooFar',
    ['hands occupied']='IGUI_CVP_LinkHandsOccupied',['held by another player']='IGUI_CVP_LinkHeldByOther',
    ['end not free']='IGUI_CVP_ConnectionChanged',['end not held']='IGUI_CVP_ConnectionChanged',
    ['different floors']='IGUI_CVP_BodyFloor',
    ['only one extra rope']='IGUI_CVP_LinkExtendLimit',['equipment return pending']='IGUI_CVP_LinkReturnPending',
}
return function(reason)
    if type(reason)=='string' and reason:match('^IGUI_CVP_[%w]+$') then return reason end
    return messages[reason] or 'IGUI_CVP_ActionFailed'
end
