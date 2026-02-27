import React, {useEffect} from 'react'
import { MapContainer, TileLayer, Marker, useMap } from 'react-leaflet'
import L from 'leaflet'

const markerIcon = new L.Icon({
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  iconSize: [25,41],
  iconAnchor: [12,41]
})

function AutoPan({position}){
  const map = useMap()
  useEffect(()=>{
    if(position) map.setView(position, map.getZoom(), {animate:true})
  },[position, map])
  return null
}

export default function LiveMap({position}){
  const center = position || [37.7749, -122.4194]
  return (
    <MapContainer center={center} zoom={13} style={{height:'100%', borderRadius:8}}>
      <TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      {position && <Marker position={position} icon={markerIcon} />}
      <AutoPan position={position} />
    </MapContainer>
  )
}
